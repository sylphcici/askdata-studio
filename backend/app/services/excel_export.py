from __future__ import annotations

from html import escape
from typing import Any


def build_excel_xml(
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> bytes:
    """生成无需额外依赖、可由Excel直接打开的SpreadsheetML文件。"""

    def cell(value: Any, style: str = "Data") -> str:
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        kind = "Number" if is_number else "String"
        return (
            f'<Cell ss:StyleID="{style}"><Data ss:Type="{kind}">'
            f"{escape(str(value if value is not None else ''))}</Data></Cell>"
        )

    merge = max(0, len(columns) - 1)
    title_row = (
        f'<Row ss:Height="30"><Cell ss:StyleID="Title" ss:MergeAcross="{merge}">'
        f'<Data ss:Type="String">{escape(title)}</Data></Cell></Row>'
    )
    meta_row = (
        f'<Row><Cell ss:StyleID="Meta" ss:MergeAcross="{merge}">'
        f'<Data ss:Type="String">完整导出 · 共 {len(rows)} 行</Data></Cell></Row>'
    )
    header = f"<Row>{''.join(cell(column, 'Header') for column in columns)}</Row>"
    data = "".join(
        f"<Row>{''.join(cell(row.get(column)) for column in columns)}</Row>"
        for row in rows
    )
    workbook = f'''<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="Default"><Font ss:FontName="Microsoft YaHei" ss:Size="10"/></Style>
  <Style ss:ID="Title"><Font ss:FontName="Microsoft YaHei" ss:Size="16" ss:Bold="1"/></Style>
  <Style ss:ID="Meta"><Font ss:FontName="Microsoft YaHei" ss:Size="9" ss:Color="#718078"/></Style>
  <Style ss:ID="Header"><Font ss:FontName="Microsoft YaHei" ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#246B4E" ss:Pattern="Solid"/></Style>
  <Style ss:ID="Data"/>
 </Styles>
 <Worksheet ss:Name="查询结果"><Table>{title_row}{meta_row}{header}{data}</Table></Worksheet>
</Workbook>'''
    return b"\xef\xbb\xbf" + workbook.encode("utf-8")
