import scrapy
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from scrapy import Selector

from .utils import (
    process_desc,
    download_cover,
    get_novel_title,
    get_chapter_id,
    make_directories,
    set_log_level,
)
from .novel_preview import novel_preview
from .doc import create_desc_doc, create_chapter_doc
from .txt import create_desc_txt, create_chapter_txt
from .font_decrypt import decrypt_jjwxc_list
from rich.panel import Panel
from rich import print
import re
from .config import format


class NovelSpider(scrapy.Spider):
    name = "novel"

    def __init__(self, id=None, yes="True", jjwxc_headers=None, *args, **kwargs):
        set_log_level()
        super(NovelSpider, self).__init__(*args, **kwargs)

        self.allowed_domains = ["www.jjwxc.net", "my.jjwxc.net"]
        self.start_urls = [f"https://www.jjwxc.net/onebook.php?novelid={id}"]
        self.id = str(id)
        self.assume_yes = yes == "True" and True or False
        self.parsed = False
        self.downloaded = False
        self.jjwxc_headers = jjwxc_headers

    def start_requests(self):
        cookies = {}
        headers = {}
        if self.jjwxc_headers:
            if 'cookie' in self.jjwxc_headers:
                cookie_str = self.jjwxc_headers['cookie']
                for item in cookie_str.split(';'):
                    if '=' in item:
                        k, v = item.split('=', 1)
                        cookies[k.strip()] = v.strip()
            if 'User-Agent' in self.jjwxc_headers:
                headers['User-Agent'] = self.jjwxc_headers['User-Agent']
        
        # Save headers to be used in subsequent requests
        self.request_headers = headers
        self.request_cookies = cookies
        self.driver = None

        for url in self.start_urls:
            yield scrapy.Request(url, cookies=cookies, headers=headers)

    def get_selenium_driver(self):
        if not hasattr(self, 'driver') or self.driver is None:
            chrome_options = Options()
            # Use new headless mode for better detection avoidance
            chrome_options.add_argument("--headless=new") 
            
            if self.jjwxc_headers and 'User-Agent' in self.jjwxc_headers:
                chrome_options.add_argument(f"user-agent={self.jjwxc_headers['User-Agent']}")
            
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Domain for cookies - navigate to domain first
            try:
                self.driver.get("https://my.jjwxc.net/404") 
                if self.jjwxc_headers and 'cookie' in self.jjwxc_headers:
                     cookie_str = self.jjwxc_headers['cookie']
                     for item in cookie_str.split(';'):
                        if '=' in item:
                            k, v = item.split('=', 1)
                            # Add to domain
                            self.driver.add_cookie({'name': k.strip(), 'value': v.strip(), 'domain': '.jjwxc.net', 'path': '/'})
            except Exception as e:
                print(f"[yellow]Selenium driver init warning: {e}[/]")

        return self.driver

    def closed(self, reason):
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()
        # Call original close logic if needed (though 'close' isn't standard Scrapy hook, 'closed' is)
        if hasattr(self, 'close') and callable(self.close):
             # The original code has a close method that takes 'spider' as arg
             self.close(self)

    def parse(self, response):
        self.parsed = True
        download = novel_preview(self.id, response, self.assume_yes)
        if not download:
            return

        novel = self.get_novel_item(response)
        self.directory = make_directories(novel)
        if novel["tag_list"] != None:
            if format == "docx":
                create_desc_doc(self.directory, novel)
            elif format == "txt":
                create_desc_txt(self.directory, novel)
            download_cover(self.directory, novel)
            self.downloaded = True

        chapters = response.css("span div a")
        
        # Also try to find VIP chapters which might be in a table
        if not chapters:
             # Try broader selector that catches both free and VIP links
             # VIP links: http://my.jjwxc.net/onebook_vip.php?...
             # Free links: http://www.jjwxc.net/onebook.php?...
             chapters = response.xpath('//tr[@itemprop="chapter"]//a[@itemprop="url"]')
        
        if not chapters:
             # Fallback: Look for any links that look like chapter links
             chapters = response.xpath('//a[contains(@href, "chapterid=")]')

        if not chapters:
            yield response.follow(response.url, callback=self.parse_chapter, headers=self.request_headers, cookies=self.request_cookies)
        else:
            for chapter in chapters:
                print(chapter)
                try:
                    # VIP chapters might use 'rel' attribute instead of 'href'
                    url = chapter.attrib.get("href")
                    if not url or url == "#" or "javascript" in url:
                        url = chapter.attrib.get("rel")
                    
                    if url:
                        yield response.follow(url, callback=self.parse_chapter, headers=self.request_headers, cookies=self.request_cookies)
                except:
                    continue

    def get_novel_item(self, response):
        novel = {}
        novel["id"] = self.id
        novel["title"] = get_novel_title(response)
        if novel["title"] == None:
            return
        novel["cover_url"] = response.css("img.noveldefaultimage::attr(src)").get()
        page_title = response.css("title::text").get()
        if re.findall("小树苗", page_title) != []:
            return get_children_novel_item(self.id, novel["title"], response)
        smallreadbody = response.css("div.smallreadbody span::text")
        if smallreadbody == []:
            novel["desc"] = response.css("div.smallreadbody::text").getall()
            (
                novel["tag_list"],
                novel["keywords"],
                novel["oneliner"],
                novel["meaning"],
            ) = (None, None, None, None)
        else:
            novel["desc"] = process_desc(response.xpath('//*[@id="novelintro"]/node()'))
            novel["tag_list"] = response.css("div.smallreadbody span a::text").getall()
            novel["oneliner"] = smallreadbody[-2].get()
            novel["meaning"] = smallreadbody[-1].get().strip()
        return novel

    def parse_chapter(self, response):
        chapter = {}
        chapter["id"] = get_chapter_id(response.url)
        # Try multiple selectors for the title as layout might change for VIP chapters
        chapter["title"] = response.css("div.novelbody div div h2::text").get()
        
        if chapter["title"] == None:
             # Try fallback for VIP chapters or different layouts
            chapter["title"] = response.css("h2::text").get()

        if chapter["title"] == None:
            # Try to see if it's a VIP chapter with a different structure
            print(f"[bold red]Failed to parse title for chapter {chapter['id']} url: {response.url}[/]")
            # Check for common error messages or lock indicators
            if "VIP" in response.text or "购买" in response.text:
                 print(f"[yellow]Detected VIP/Locked content indicators for {response.url}[/]")
            return
            
        
        # Try to find VIP content container first (div with id starting with 'content_')
        # The content might be in children nodes, so we need to be recursive or careful
        vip_content_div = response.xpath("//div[starts-with(@id, 'content_')]")
        
        # Check if the extracted content contains the error message
        full_text = ""
        if vip_content_div:
             content_list = vip_content_div.xpath(".//text()[not(ancestor::script) and not(ancestor::style)]").getall()
             full_text = "".join(content_list)
             chapter["body"] = content_list
        else:
             # Fallback to standard body
             content_list = response.xpath("//div[@class='novelbody']/div/node()[not(self::script)]").getall()
             # If node() returns elements, getall returns strings including tags.
             # We want text to check for error.
             # Construct text for check
             full_text = "".join(response.xpath("//div[@class='novelbody']/div//text()").getall())
             chapter["body"] = content_list

        # If body is empty or contains error message, try Selenium
        error_indicators = ["vip内容加载中", "VIP内容加载失败", "浏览器版本可能过低"]
        if not chapter["body"] or any(err in full_text for err in error_indicators):
             print(f"[yellow]Standard fetch failed for {chapter['title']} (Error detected), trying Selenium...[/]")
             try:
                 driver = self.get_selenium_driver()
                 driver.get(response.url)
                 
                 # Wait for the content div
                 WebDriverWait(driver, 20).until(
                     EC.presence_of_element_located((By.XPATH, "//div[starts-with(@id, 'content_')]"))
                 )
                 
                 # Get the inner HTML of the body container
                 # We get the 'novelbody' or the specific content div
                 # Finding the specific content div is safer
                 content_element = driver.find_element(By.XPATH, "//div[starts-with(@id, 'content_')]")
                 body_html = content_element.get_attribute("outerHTML")
                 
                 # Create a new Selector
                 sel = Selector(text=body_html)
                 
                 # Extract content using the same logic
                 vip_content_div = sel.xpath("//div[starts-with(@id, 'content_')]")
                 if vip_content_div:
                      chapter["body"] = vip_content_div.xpath(".//text()[not(ancestor::script) and not(ancestor::style)]").getall()
                 else:
                      print(f"[red]Selenium found content div but extraction failed for {chapter['title']}[/]")

             except Exception as e:
                 print(f"[bold red]Selenium extraction failed for {chapter['title']}: {e}[/]")
        
        # If body is empty, it might be a VIP chapter where content is loaded differently or we are not logged in properly
        if not chapter["body"]:
             print(f"[yellow]Warning: Empty body for chapter {chapter['title']} (ID: {chapter['id']}). Possible VIP restriction or parsing error.[/]")
             # Debug: Print a snippet of the page to see what's happening
             # print(response.text[:500])

        # 使用对照表解码字体混淆的内容
        if chapter.get("body"):
            chapter["body"] = decrypt_jjwxc_list(chapter["body"])
            print(f"[green]Decrypted chapter content using font mapping table[/]")

        chapter["author_said"] = process_desc(response.css("div.readsmall"))
        if format == "docx":
            create_chapter_doc(self.directory, chapter)
        elif format == "txt":
            create_chapter_txt(self.directory, chapter)

    def close(self, spider):
        if not self.parsed:
            print(
                Panel(
                    "      非常抱歉，相关内容已被锁定或删除。",
                    style="bold red",
                    border_style="bright_white",
                    width=48,
                )
            )
        else:
            try:
                if self.downloaded:
                    print(f"下载完毕！（下载路径为 {self.directory} ）")
            except:
                pass


def get_children_novel_item(id, title, response):
    novel = {}
    novel["id"] = id
    novel["title"] = title
    novel_meta = response.css("div.novelmeta_item_div span::text")
    novel["desc"] = process_desc(
        response.xpath("//div[@class='novelmeta_item_div']/span")[10].css("*").getall()
    )
    novel["tag_list"] = response.css("span span a::text").getall()
    novel["keywords"] = novel_meta[-6].get() + novel_meta[-5].get()
    novel["oneliner"] = novel_meta[-4].get() + novel_meta[-3].get()
    novel["meaning"] = novel_meta[-2].get() + novel_meta[-1].get()
    return novel
