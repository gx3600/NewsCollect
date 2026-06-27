"""Daily futures variety updater — fetches from 同花顺 API and writes to Excel.

Reference: DataInit.java in the ExcelToWord project.
API: https://ftapi.10jqka.com.cn/futgwapi/api/data/quote_tab/v1/config?type=domestic

Usage:
    from news_collect.utils.variety_updater import update_futures_variety
    success = update_futures_variety()
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── API endpoint ─────────────────────────────────────────────────
API_URL = "https://ftapi.10jqka.com.cn/futgwapi/api/data/quote_tab/v1/config?type=domestic"

# ── Filter lists (ported from Define.java) ──────────────────────

# Tab names to exclude (exchange-level tabs and monthly avg)
TAB_NAME_FILTER = {"上期所", "大商所", "郑商所", "上期能源", "广期所", "中金所", "月均价"}

# Contract names to exclude (financial futures + livestock)
CONTRACT_NAME_FILTER = {
    "上证50", "沪深300", "中证500", "中证1000",
    "十年国债", "五年国债", "二年国债", "三十年国债",
    "生猪", "鸡蛋",
}

# ── Keywords mapping (ported from Define.typeMap()) ─────────────

KEYWORDS_MAP: dict[str, str] = {
    # 化工类
    "20号胶": "20号胶,橡胶,标胶",
    "LPG": "LPG,液化气,丙烷",
    "PTA": "PTA,精对苯二甲酸",
    "PVC": "PVC,聚氯乙烯,塑料",
    "乙二醇": "乙二醇,EG,甘醇",
    "丙烯": "丙烯,烯烃,化工原料",
    "合成橡胶": "合成橡胶,丁二烯,合成胶",
    "天然橡胶": "橡胶,NR",
    "对二甲苯": "二甲苯,PX,芳烃",
    "尿素": "尿素,脲,氮肥",
    "工业硅": "硅",
    "甲醇": "甲醇,木醇,煤化工",
    "塑料": "塑料,PVC,聚乙烯",
    "纯苯": "苯,芳烃,化工基础原料",
    "苯乙烯": "苯乙烯,PS",
    "短纤": "短纤,短纤维",
    "纸浆": "纸浆,木浆,造纸原料",
    "聚丙烯": "丙烯,PP,聚丙",
    "双胶纸": "双胶,胶版纸",
    "烧碱": "烧碱,氢氧化钠",
    "玻璃": "玻璃,平板玻璃",
    "瓶片": "瓶片,聚酯瓶片",
    "纯碱": "纯碱,碳酸钠",
    # 能源类
    "原油": "原油,石油",
    "低硫燃油": "燃油,船用油",
    "动力煤": "煤",
    "动煤": "煤",
    "焦炭": "焦炭,冶金焦",
    "焦煤": "焦煤,主焦煤,炼焦煤",
    "燃油": "燃油,重油,船用油",
    "沥青": "沥青,石油沥青",
    # 金属类
    "不锈钢": "不锈钢,铬镍钢",
    "沪铅": "铅,Pb",
    "沪铜": "铜,Cu",
    "沪铝": "铝,Al",
    "沪锌": "锌,Zn",
    "沪锡": "锡,Sn",
    "沪镍": "镍,Ni",
    "沪金": "沪金,金价,金银,Au",
    "沪银": "沪银,银价,金银,Ag",
    "氧化铝": "铝,矾土",
    "碳酸锂": "锂",
    "多晶硅": "多晶硅,硅料",
    "国际铜": "铜",
    "钯": "钯,Pd",
    "铂": "铂,Pt",
    "铝合金": "铝",
    "硅铁": "铁,硅铁",
    "锰硅": "锰,锰硅",
    "铁矿石": "铁矿",
    "螺纹钢": "钢",
    "热卷": "热卷,热轧卷板",
    "线材": "线材,盘条",
    # 农产品类
    "强麦": "麦",
    "早籼稻": "稻",
    "普麦": "麦",
    "棉纱": "纱,棉",
    "棉花": "棉",
    "棕榈油": "棕榈,棕油",
    "花生": "花生",
    "苹果": "苹",
    "菜油": "菜油,菜籽油",
    "菜籽": "菜籽",
    "菜粕": "菜粕,菜籽粕",
    "豆一": "豆",
    "豆二": "豆",
    "豆油": "豆油",
    "豆粕": "豆粕",
    "玉米": "玉米,苞米",
    "玉米淀粉": "玉米,淀粉",
    "白糖": "糖",
    "粳稻": "稻",
    "粳米": "米,粳",
    "红枣": "枣",
    "生猪": "猪",
    "鸡蛋": "蛋",
    # 木材类
    "原木": "木",
    "纤维板": "纤维板,密度板",
    "胶合板": "胶合板,多层板",
    # 金融期货类 (in map for completeness, but filtered out)
    "三十年国债": "国债,利率债",
    "上证50": "上证50,股指",
    "中证1000": "中证,股指",
    "中证500": "中证,股指",
    "二年国债": "国债,利率债",
    "五年国债": "国债,利率债",
    "十年国债": "国债,利率债",
    "沪深300": "沪深300,股指",
}


def _get_output_path(filename: str = "futures_variety.xlsx") -> Path:
    """Resolve the output Excel path relative to the project root."""
    # Project root is 3 levels up from this file
    base = Path(__file__).parent.parent.parent
    return base / "config" / filename


def fetch_varieties_from_api(timeout: int = 30) -> Optional[list[dict]]:
    """Fetch futures varieties from the 同花顺 API.

    Returns a list of dicts with keys: tabName, market, contract, contractName, keyWords.
    Returns None on failure.
    """
    try:
        resp = requests.get(API_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch futures varieties API: {e}")
        return None
    except ValueError as e:
        logger.error(f"Failed to parse API JSON response: {e}")
        return None

    if data.get("code") != 0:
        logger.error(f"API returned error: code={data.get('code')}, msg={data.get('msg')}")
        return None

    tab_list = data.get("data", {}).get("tab_list", [])
    if not tab_list:
        logger.warning("API returned empty tab_list")
        return []

    result: list[dict] = []

    for tab in tab_list:
        tab_name = tab.get("tab_name", "")

        # Filter: skip exchange-level and monthly-avg tabs
        if tab_name in TAB_NAME_FILTER:
            continue

        contract_map = tab.get("contract_map", {})
        varieties = contract_map.get("variety", [])

        for v in varieties:
            contract_name = v.get("contract_name", "")

            # Filter: skip financial futures + livestock
            if contract_name in CONTRACT_NAME_FILTER:
                continue

            market = v.get("market", "")
            contract = v.get("contract", "")

            # Resolve keywords: from map, fallback to contract_name itself
            keywords = KEYWORDS_MAP.get(contract_name)
            if not keywords:
                keywords = contract_name

            result.append({
                "tabName": tab_name,
                "market": market,
                "contract": contract,
                "contractName": contract_name,
                "keyWords": keywords,
            })

    return result


def write_varieties_to_excel(
    data: list[dict],
    output_path: Optional[Path] = None,
) -> bool:
    """Write the variety data to an Excel file using openpyxl.

    Creates the file with columns: tabName, market, contract, contractName, keyWords.
    Writes to a temp file first, then replaces the target atomically to handle
    file-lock situations (e.g. Excel has the file open).
    """
    if output_path is None:
        output_path = _get_output_path()

    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed — cannot write Excel file.")
        return False

    import tempfile
    import os
    import time

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "期货品种数据"

        # Header row
        ws.append(["tabName", "market", "contract", "contractName", "keyWords"])

        # Data rows
        for row in data:
            ws.append([
                row["tabName"],
                row["market"],
                row["contract"],
                row["contractName"],
                row["keyWords"],
            ])

        # Write to a temp file in the same directory (same filesystem = atomic rename)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(output_path.parent),
            prefix=".futures_variety_",
            suffix=".xlsx",
        )
        os.close(tmp_fd)
        wb.save(tmp_path)
        wb.close()

        # Replace the target file
        if output_path.exists():
            backup = output_path.with_suffix(".xlsx.bak")
            try:
                output_path.replace(backup)
            except PermissionError:
                # Can't move the locked file — try direct overwrite
                pass

        # Move temp to target
        try:
            os.replace(tmp_path, str(output_path))
        except PermissionError:
            # Target still locked. Try a few times with short waits.
            for attempt in range(3):
                time.sleep(1)
                try:
                    os.replace(tmp_path, str(output_path))
                    break
                except PermissionError:
                    if attempt == 2:
                        logger.error(
                            f"Cannot write to {output_path} — file is locked "
                            f"(e.g. open in Excel). Temp file saved at {tmp_path}"
                        )
                        return False

        logger.info(
            f"Wrote {len(data)} futures varieties to {output_path}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to write Excel file {output_path}: {e}")
        return False


def update_futures_variety(
    output_path: Optional[Path] = None,
    timeout: int = 30,
) -> bool:
    """Fetch latest futures varieties from API and update the Excel file.

    This is the main entry point. Returns True on success.

    Usage:
        success = update_futures_variety()
    """
    logger.info("Fetching latest futures varieties from API...")
    data = fetch_varieties_from_api(timeout=timeout)

    if data is None:
        logger.error("Aborting update — API fetch failed.")
        return False

    if not data:
        logger.warning("Aborting update — API returned empty data.")
        return False

    logger.info(f"Fetched {len(data)} varieties. Writing to Excel...")
    success = write_varieties_to_excel(data, output_path=output_path)

    if success:
        # Invalidate the Config singleton's variety cache so it reloads
        _invalidate_config_cache()

    return success


def _invalidate_config_cache():
    """Clear the Config singleton's variety cache so next access reloads."""
    try:
        from news_collect.utils.config import Config
        cfg = Config()
        cfg._variety_cache = None
        logger.info("Config variety cache invalidated — will reload on next access.")
    except Exception as e:
        logger.debug(f"Could not invalidate config cache: {e}")


# ── CLI entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    success = update_futures_variety()
    sys.exit(0 if success else 1)
