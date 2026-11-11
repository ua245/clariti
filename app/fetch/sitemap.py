import gzip
from io import BytesIO
from urllib.parse import urlsplit

from defusedxml import ElementTree


MAX_XML_BYTES = 2 * 1024 * 1024
MAX_URLS = 500


def parse_sitemap(content: bytes) -> list[str]:
    if len(content) > MAX_XML_BYTES:
        raise ValueError("Sitemap exceeds 2 MiB limit.")
    if content.startswith(b"\x1f\x8b"):
        content = gzip.GzipFile(fileobj=BytesIO(content)).read(MAX_XML_BYTES + 1)
        if len(content) > MAX_XML_BYTES:
            raise ValueError("Decompressed sitemap exceeds 2 MiB limit.")
    start = content.find(b"<")
    if start < 0:
        raise ValueError("Sitemap does not contain XML.")
    try:
        root = ElementTree.fromstring(content[start:])
    except ElementTree.ParseError as error:
        raise ValueError("Malformed sitemap XML.") from error
    urls = []
    for element in root.findall(".//{*}loc"):
        if element.text and element.text.strip():
            urls.append(element.text.strip())
    return list(dict.fromkeys(urls))[:MAX_URLS]
