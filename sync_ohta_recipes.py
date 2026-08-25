import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.osakafoodstyle.com"
ARCHIVE_URL = f"{BASE_URL}/recipe/"
CSV_PATH = Path("fa2ac34592382d85a2af03a450f780a4.csv")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; OsakaFoodStyleOhtaSync/1.0; +https://www.osakafoodstyle.com/)"
})


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = re.sub(r"[\s\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]+", "", parsed.path)
    path = re.sub(r"/+", "/", path)
    if path.startswith("/recipe/") and not path.endswith("/"):
        path += "/"
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))


def get(url: str) -> requests.Response:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response


def is_recipe_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") + "/"
    if parsed.netloc and parsed.netloc not in {"www.osakafoodstyle.com", "osakafoodstyle.com"}:
        return False
    return path.startswith("/recipe/") and path != "/recipe/" and not path.startswith("/recipe/page/")


def collect_recipe_urls(max_pages: int = 60) -> list[str]:
    found = []
    seen = set()
    previous = None
    for page in range(1, max_pages + 1):
        url = ARCHIVE_URL if page == 1 else f"{ARCHIVE_URL}page/{page}/"
        try:
            response = get(url)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if page > 1 and status in {404, 410}:
                break
            raise
        soup = BeautifulSoup(response.text, "html.parser")
        page_urls = set()
        for a in soup.find_all("a", href=True):
            href = normalize_url(urljoin(response.url, a["href"]))
            if is_recipe_detail_url(href):
                page_urls.add(href)
        if not page_urls or page_urls == previous:
            break
        previous = page_urls
        for recipe_url in sorted(page_urls):
            if recipe_url not in seen:
                seen.add(recipe_url)
                found.append(recipe_url)
        print(f"archive page {page}: {len(page_urls)} recipes")
        time.sleep(0.1)
    print(f"public archive recipe URLs: {len(found)}")
    return found


def inner_html(node) -> str:
    if not node:
        return ""
    return "".join(str(child) for child in node.contents)


def find_main_content(soup: BeautifulSoup):
    selectors = [
        "article .entry-content",
        ".entry-content",
        "article",
        "main",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) > 100:
            return node
    return soup.body or soup


def extract_taxonomy(soup: BeautifulSoup, prefix: str) -> list[str]:
    values = []
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, a["href"])
        if prefix not in urlparse(href).path:
            continue
        text = a.get_text(" ", strip=True)
        if text and text not in values:
            values.append(text)
    return values


def parse_recipe(url: str, fieldnames: list[str]) -> dict[str, str]:
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    title_node = soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not title:
        og = soup.find("meta", property="og:title")
        title = og.get("content", "").strip() if og else ""
    title = re.sub(r"\s*[|｜].*$", "", title).strip()

    content_node = find_main_content(soup)
    content = inner_html(content_node)

    image_urls = []
    for img in content_node.find_all("img") if content_node else []:
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        if not src:
            continue
        src = urljoin(response.url, src)
        if "wp-content/uploads" in src and src not in image_urls:
            image_urls.append(src)

    seasons = extract_taxonomy(soup, "/recipe_season/")
    types = extract_taxonomy(soup, "/recipe_type/")

    row = {name: "" for name in fieldnames}
    mapping = {
        "Title": title,
        "Content": content,
        "Post Type": "recipe",
        "Permalink": normalize_url(response.url),
        "Image URL": "|".join(image_urls),
        "季節": "|".join(seasons),
        "種類": "|".join(types),
        "Status": "publish",
    }
    for key, value in mapping.items():
        if key in row:
            row[key] = value
    return row


def main() -> int:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    existing = {
        normalize_url(row.get("Permalink", ""))
        for row in rows
        if row.get("Post Type") == "recipe" and row.get("Permalink")
    }
    print(f"existing recipe rows: {len(existing)}")

    public_urls = collect_recipe_urls()
    missing = [url for url in public_urls if url not in existing]
    print(f"missing published recipes: {len(missing)}")

    if not missing:
        print("ohta CSV is already up to date.")
        return 0

    added = []
    for index, url in enumerate(missing, 1):
        print(f"[{index}/{len(missing)}] {url}")
        try:
            row = parse_recipe(url, fieldnames)
            added.append(row)
            print(f"  added: {row.get('Title', '')}")
        except Exception as exc:
            print(f"  WARN parse failed: {exc}")
        time.sleep(0.15)

    if added:
        with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(added + rows)
        print(f"updated ohta CSV with {len(added)} recipes")
    else:
        print("No recipes could be added.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
