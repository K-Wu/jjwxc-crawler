"""
晋江文学城字体解码模块

使用 font-decrypt 目录中的对照表将 Unicode 乱码转换为正确汉字。
对照表格式: &#xE016;-天 (Unicode码点 -> 汉字)
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional


class JJWXCFontDecrypt:
    """晋江字体解码器，使用预置的对照表"""

    def __init__(self):
        self.char_map: Dict[str, str] = {}
        self._load_all_mappings()

    def _load_all_mappings(self):
        """加载所有对照表文件"""
        # 获取 font-decrypt 目录路径
        current_dir = Path(__file__).parent
        font_decrypt_dir = current_dir.parent.parent.parent / "font-decrypt"

        if not font_decrypt_dir.exists():
            print(f"[yellow]Warning: font-decrypt directory not found at {font_decrypt_dir}[/]")
            return

        # 加载所有 .txt 对照表文件
        for txt_file in font_decrypt_dir.glob("jjwxcfont_*.txt"):
            self._load_mapping_file(txt_file)

        print(f"[green]Loaded {len(self.char_map)} character mappings from font-decrypt[/]")

    def _load_mapping_file(self, file_path: Path):
        """加载单个对照表文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # 解析格式: &#xE016;-天
                    match = re.match(r'&#x([0-9A-Fa-f]+);-(.)', line)
                    if match:
                        hex_code = match.group(1)
                        char = match.group(2)
                        try:
                            unicode_char = chr(int(hex_code, 16))
                            self.char_map[unicode_char] = char
                        except ValueError:
                            pass
        except Exception as e:
            print(f"[yellow]Warning: Failed to load {file_path}: {e}[/]")

    def decrypt(self, text: str) -> str:
        """解码文本中的乱码字符"""
        if not self.char_map:
            return text

        result = []
        for char in text:
            if char in self.char_map:
                result.append(self.char_map[char])
            else:
                result.append(char)

        return ''.join(result)

    def decrypt_list(self, text_list: list) -> list:
        """解码文本列表"""
        return [self.decrypt(text) for text in text_list]


# 全局实例
_decryptor: Optional[JJWXCFontDecrypt] = None


def get_decryptor() -> JJWXCFontDecrypt:
    """获取全局解码器实例"""
    global _decryptor
    if _decryptor is None:
        _decryptor = JJWXCFontDecrypt()
    return _decryptor


def decrypt_jjwxc_text(text: str) -> str:
    """便捷函数：解码晋江文本"""
    return get_decryptor().decrypt(text)


def decrypt_jjwxc_list(text_list: list) -> list:
    """便捷函数：解码晋江文本列表"""
    return get_decryptor().decrypt_list(text_list)
