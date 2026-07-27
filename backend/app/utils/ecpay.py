import hashlib
import os
import urllib.parse

# 綠界測試環境 (Stage) 官方公開的測試用 HashKey / HashIV，正式上線需改用商店後台取得的正式金鑰。
ECPAY_HASH_KEY = os.environ.get("ECPAY_HASH_KEY", "5294y06JbISpM5x9")
ECPAY_HASH_IV = os.environ.get("ECPAY_HASH_IV", "v77hoKGq4kWxNNIS")

# .NET 的 UrlEncode 對這幾個字元的編碼方式跟 Python 內建的不同，需要換回來才會跟綠界那邊算出一致的雜湊值。
_DOTNET_ENCODE_FIXUPS = {
    "%2d": "-",
    "%5f": "_",
    "%2e": ".",
    "%21": "!",
    "%2a": "*",
    "%28": "(",
    "%29": ")",
}


def generate_check_mac_value(params, hash_key=None, hash_iv=None):
    """依綠界規範，將參數字典算出 CheckMacValue。

    步驟：依 key 字母排序 -> 前後夾上 HashKey/HashIV -> URL encode 後轉小寫 ->
    修正 .NET 與 Python URL encode 的差異字元 -> SHA256 -> 轉大寫。
    """
    hash_key = hash_key or ECPAY_HASH_KEY
    hash_iv = hash_iv or ECPAY_HASH_IV

    sorted_items = sorted(params.items(), key=lambda item: item[0])
    raw = "HashKey={}&{}&HashIV={}".format(
        hash_key,
        "&".join(f"{key}={value}" for key, value in sorted_items),
        hash_iv,
    )

    encoded = urllib.parse.quote_plus(raw).lower()
    for encoded_char, replacement in _DOTNET_ENCODE_FIXUPS.items():
        encoded = encoded.replace(encoded_char, replacement)

    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()
