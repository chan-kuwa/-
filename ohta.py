import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import google.generativeai as genai
import base64
import io
import re
from collections import Counter
from itertools import combinations
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

# --- 1. ページ設定 ---
st.set_page_config(
    page_title="レシピ検索アプリ",
    page_icon="logo.png",
    layout="wide"
)

# サイドバー非表示＋スマホ向け表示調整
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {display: none;}
    [data-testid="collapsedControl"] {display: none;}

    .app-header { margin: 0 0 1.2rem 0; }
    .app-brand-row {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        flex-wrap: nowrap;
        white-space: nowrap;
        margin-left: 0;
    }
    .app-brand-row img {
        width: 48px;
        height: auto;
        flex: 0 0 auto;
    }
    .app-title-line,
    .app-main-title,
    .search-heading {
        font-size: clamp(22px, 7vw, 36px);
        font-weight: 700;
        line-height: 1.2;
        white-space: nowrap;
    }
    .app-title-line { margin: 0; }
    .app-main-title { margin: 0.35rem 0 0.45rem 0; }
    .app-caption {
        color: #7a7a7a;
        font-size: clamp(12px, 3vw, 15px);
        margin-bottom: 1.2rem;
    }
    .search-heading { margin: 1.2rem 0 1rem 0; }

    @media (max-width: 480px) {
        .block-container {
            padding-left: 12px !important;
            padding-right: 12px !important;
        }
        .app-header,
        .app-brand-row,
        .app-main-title,
        .app-caption,
        .search-heading { margin-left: 0 !important; }
        .app-brand-row img { width: 34px; }
        .app-brand-row { gap: 0.4rem; }
        .app-title-line,
        .app-main-title,
        .search-heading {
            font-size: 24px;
            line-height: 1.2;
            letter-spacing: -0.3px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- 2. 認証機能 ---
def check_password():
    if st.session_state.get("password_correct", False):
        return True

    st.title("🔐 認証が必要です")
    password = st.text_input("password", type="password")

    if st.button("ログイン"):
        target_password = st.secrets.get("APP_PASSWORD", "0000")
        if password == target_password:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False


# --- PDF作成 ---
def _register_japanese_font():
    font_name = "HeiseiMin-W3"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    return font_name


def _markdown_to_plain(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text.strip()


def make_recipe_pdf(text):
    buffer = io.BytesIO()
    font_name = _register_japanese_font()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="生成された文章とレシピ",
        author="やさい料理研究家 大畑ちつる",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "JPTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=16,
        leading=22,
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "JPBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10.5,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=5,
    )

    story = [Paragraph("やさい料理研究家 大畑ちつる", title_style), Spacer(1, 3 * mm)]
    plain = _markdown_to_plain(text)
    for block in plain.split("\n"):
        line = block.strip()
        if line:
            story.append(Paragraph(escape(line), body_style))
        else:
            story.append(Spacer(1, 2.5 * mm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# --- CSV全体から味付け・調理傾向を圧縮して取り出す ---
SEASONING_TERMS = [
    "薄口しょうゆ", "濃口しょうゆ", "しょうゆ", "味噌", "白味噌", "赤味噌",
    "塩", "砂糖", "みりん", "酒", "酢", "米酢", "黒酢", "バルサミコ酢",
    "レモン", "すだち", "ゆず", "柑橘", "昆布だし", "昆布", "かつおだし",
    "ごま", "練りごま", "ごま油", "オリーブ油", "オリーブオイル", "バター",
    "ヨーグルト", "牛乳", "豆乳", "チーズ", "トマト", "トマトジュース",
    "にんにく", "しょうが", "わさび", "からし", "山椒", "こしょう",
    "カレー粉", "クミン", "コリアンダー", "唐辛子", "豆板醤", "オイスターソース",
    "はちみつ", "蜂蜜"
]

COOKING_TERMS = [
    "煮る", "煮物", "蒸す", "蒸し", "焼く", "焼き", "炒める", "炒め",
    "和える", "和え", "漬ける", "漬け", "揚げる", "揚げ", "茹でる", "ゆでる",
    "炊く", "炊き", "オーブン", "レンジ", "電子レンジ", "スープ", "サラダ"
]


def _term_counts_by_recipe(df, terms):
    counts = Counter()
    for text in df["clean_content"].fillna("").astype(str):
        for term in terms:
            if term in text:
                counts[term] += 1
    return counts


@st.cache_data
def build_csv_style_context(df):
    """CSV全体をローカル集計し、追加API消費なしで味の軸を圧縮する。"""
    seasoning_counts = _term_counts_by_recipe(df, SEASONING_TERMS)
    cooking_counts = _term_counts_by_recipe(df, COOKING_TERMS)

    pair_counts = Counter()
    for text in df["clean_content"].fillna("").astype(str):
        used = sorted({term for term in SEASONING_TERMS if term in text})
        for a, b in combinations(used, 2):
            pair_counts[(a, b)] += 1

    seasoning_text = "、".join(
        f"{term}（{count}レシピ）" for term, count in seasoning_counts.most_common(25)
    ) or "集計できる調味料情報なし"

    pair_text = "、".join(
        f"{a}＋{b}（{count}レシピ）" for (a, b), count in pair_counts.most_common(18)
    ) or "集計できる組み合わせ情報なし"

    cooking_text = "、".join(
        f"{term}（{count}レシピ）" for term, count in cooking_counts.most_common(18)
    ) or "集計できる調理法情報なし"

    season_text = ""
    if "季節" in df.columns:
        season_counts = df["季節"].fillna("不明").astype(str).value_counts()
        season_text = "、".join(f"{k}：{v}件" for k, v in season_counts.items())

    # CSV全体の幅を残すため、全体から均等に最大30件を代表例として抜き出す。
    example_lines = []
    if len(df) > 0:
        n = min(30, len(df))
        if n == 1:
            indices = [0]
        else:
            indices = sorted({round(i * (len(df) - 1) / (n - 1)) for i in range(n)})
        for idx in indices:
            row = df.iloc[idx]
            title = str(row.get("Title", ""))
            content = re.sub(r"\s+", " ", str(row.get("clean_content", ""))).strip()
            example_lines.append(f"・{title}：{content[:260]}")

    return f"""
【CSV全体から集計した料理傾向】
レシピ総数：{len(df)}件
季節内訳：{season_text or '情報なし'}
よく登場する調味料・味の要素：{seasoning_text}
よく登場する調味料の組み合わせ：{pair_text}
よく登場する調理法：{cooking_text}

【CSV全体から均等に抽出した代表レシピ】
{chr(10).join(example_lines)}
""".strip()


def _make_ngrams(text):
    normalized = re.sub(r"[\s、。,.!！?？・/／()（）\[\]「」『』]", "", text)
    stop_words = ["レシピ", "作りたい", "使って", "料理", "人分", "ください", "欲しい", "ほしい"]
    for word in stop_words:
        normalized = normalized.replace(word, "")
    grams = set()
    for size in (2, 3, 4):
        for i in range(max(0, len(normalized) - size + 1)):
            grams.add(normalized[i:i + size])
    return grams


def build_related_recipe_context(df, user_request, limit=20):
    """入力に近い過去レシピを追加で渡し、CSVらしさを具体化する。"""
    grams = _make_ngrams(user_request)
    if not grams:
        return "関連レシピの抽出なし"

    scored = []
    for _, row in df.iterrows():
        title = str(row.get("Title", ""))
        content = str(row.get("clean_content", ""))
        title_score = sum(3 for g in grams if g in title)
        content_score = sum(1 for g in grams if g in content)
        score = title_score + content_score
        if score > 0:
            scored.append((score, title, content))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[:limit]

    if not selected:
        return "関連レシピの抽出なし"

    lines = []
    for _, title, content in selected:
        compact = re.sub(r"\s+", " ", content).strip()
        lines.append(f"・{title}：{compact[:420]}")
    return "\n".join(lines)


BASE_RECIPE_RULES = """
【レシピ開発の基本方針】
・大畑ちつるの過去レシピCSV全体から読み取った、味付けのバランス、調味料の組み合わせ、野菜の扱い方、調理法の傾向をレシピ設計の最優先の軸にする
・特定の調味料には固定しない。薄口しょうゆを毎回使う必要はない
・同じような味付けや料理ばかりにならないよう、CSVにある味の幅を生かす
・塩、味噌、酢、柑橘、胡麻、スパイス、トマト、乳製品なども料理に合えば使ってよい
・新しい食材の組み合わせや調理法は、海外料理や日本の信頼できる料理メディアで一般的に使われる発想もヒントにしてよい
・外部のアイデアはそのままコピーせず、CSVから読み取れる大畑ちつるの味付け・料理設計に落とし込む
・CSVの味付けの軸を、外部アイデアより優先する
・新しさのためだけに奇抜な組み合わせにはしない

【使用しない調味料・食品】
・顆粒だしは使わない
・めんつゆは使わない
・マヨネーズは使わない
・化学調味料は使わない
・上記を代用品として提案することも禁止

【材料と味付け】
・基本は2人分
・家庭のスーパーで購入しやすい材料を使う
・野菜が主役になる構成にする
・調味料の分量は具体的に書く
・「適量」「少々」などの曖昧な表現はできるだけ避ける
・材料数と調味料数を必要以上に増やさない
・食材本来の味が分かる程度の味付けにする

【文章の雰囲気】
・やさしい温度感で、季節感と素材のおいしさが伝わる文章にする
・大阪のおばんざいらしさは残すが、関西弁は使わない
・ですます調で統一する
・冒頭は「こんにちは。やさい料理研究家の大畑ちつるです。」で始める
・過度に上品、過度に女性的な言い回しにしない
・「お出汁」「お野菜」「お料理」など、名詞に不要な「お」を付けない
・「お出汁」は使わず、「出汁」または「昆布だし」と書く
・「お野菜」ではなく「野菜」、「お料理」ではなく「料理」と書く

【禁止する文章表現】
・中央卸売市場時代の話は禁止
・昔話は禁止
・自分語りは禁止
・「淡口しょうゆ」は禁止。必ず「薄口しょうゆ」と書く
・AIっぽい説明は禁止
・「〜が特徴です」「〜を採用しました」は使わない
・必要以上に美辞麗句を重ねない
・同じ形容表現を繰り返さない

【文章量】
・冒頭文は3〜5段落ほど
・読みものとして楽しめる長さにするが、長編エッセイにはしない

【レシピ構成】
1. 挨拶
2. 季節や素材についての短い導入
3. レシピタイトル
4. 材料
5. 作り方
6. 食べた時の魅力やおすすめの食べ方

【作り方のルール】
・必ず番号をつける
・各工程に見出しをつける
・工程ごとに1〜3文で丁寧に説明する
・料理初心者でも再現できる説明にする
・火加減や加熱時間が重要な場合は具体的に書く
・切り方が味や食感に影響する場合は具体的に書く
""".strip()


# --- 3. メイン処理 ---
def main_app():
    def get_image_base64(file_path):
        try:
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return None

    img_base64 = get_image_base64("logo.png")

    if img_base64:
        st.markdown(
            f"""
            <head>
                <link rel="apple-touch-icon" href="data:image/png;base64,{img_base64}">
                <meta name="apple-mobile-web-app-title" content="大畑ちつるレシピ">
                <meta name="apple-mobile-web-app-capable" content="yes">
            </head>
            """,
            unsafe_allow_html=True
        )
        st.markdown(
            f"""
            <div class="app-header">
                <div class="app-brand-row">
                    <img src="data:image/png;base64,{img_base64}">
                    <div class="app-title-line">やさい料理研究家 大畑ちつる</div>
                </div>
                <div class="app-main-title">レシピリサーチ＆レシピメーカー</div>
                <div class="app-caption">日々の献立作りをサポートする、プロの野菜レシピ検索ツールです。</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div class="app-header">
                <div class="app-title-line">やさい料理研究家 大畑ちつる</div>
                <div class="app-main-title">レシピリサーチ＆レシピメーカー</div>
                <div class="app-caption">日々の献立作りをサポートする、プロの野菜レシピ検索ツールです。</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        st.error("GOOGLE_API_KEYが見つかりません。")
        return

    model_instance = genai.GenerativeModel("gemini-3-flash-preview")

    @st.cache_data
    def load_data(file_path):
        df = pd.read_csv(file_path)
        df = df[df["Post Type"] == "recipe"].copy()

        def strip_html(html_str):
            if pd.isna(html_str):
                return ""
            return BeautifulSoup(html_str, "html.parser").get_text(separator=" ").strip()

        df["clean_content"] = df["Content"].apply(strip_html)
        return df

    master_csv = Path("master_recipe_data.csv")
    legacy_csv = Path("fa2ac34592382d85a2af03a450f780a4.csv")
    active_csv = master_csv if master_csv.exists() else legacy_csv
    df = load_data(str(active_csv))
    csv_style_context = build_csv_style_context(df)

    if "季節" in df.columns:
        all_seasons = df["季節"].dropna().unique().tolist()
    else:
        all_seasons = ["春", "夏", "秋", "冬"]

    st.markdown("### 今日は何をしますか？")
    mode = st.radio(
        "メニュー",
        ["過去レシピを検索", "自由な食材から新作を生成"],
        index=None,
        key="main_mode",
        label_visibility="collapsed",
        horizontal=True
    )

    if mode is None:
        st.caption("やりたいことを選んでください。")
        return

    # --- 過去レシピ検索 ---
    if mode == "過去レシピを検索":
        st.markdown('<div class="search-heading">🔍過去レシピ検索</div>', unsafe_allow_html=True)
        q = st.text_input("キーワードを入力（食材や料理名）", placeholder="例：なす 豚肉")

        st.markdown("### 季節・旬を選択")
        selected_seasons = st.multiselect(
            "季節・旬",
            options=all_seasons,
            default=all_seasons,
            key="main_seasons",
            label_visibility="collapsed"
        )

        filtered_df = df[df["季節"].isin(selected_seasons)] if selected_seasons else df.iloc[0:0]

        if q:
            keywords = q.split()
            mask = filtered_df["clean_content"].str.contains(keywords[0], na=False, case=False)
            for kw in keywords[1:]:
                mask &= filtered_df["clean_content"].str.contains(kw, na=False, case=False)

            results = filtered_df[mask]
            st.write(f"ヒット数: {len(results)}件")
            for _, row in results.head(10).iterrows():
                with st.expander(f"📖 {row['Title']}"):
                    if pd.notna(row["Image URL"]):
                        st.image(row["Image URL"].split("|")[0], width=300)
                    st.markdown(f"**[元記事を見る]({row['Permalink']})**")
                    st.write(row["clean_content"])
                    st.divider()
                    st.caption("コピーして献立メモなどに貼り付けられます ↓")
                    copy_text = f"【{row['Title']}】\n\n{row['clean_content']}\n\n元記事: {row['Permalink']}"
                    st.code(copy_text, language="text")

    # --- 新作レシピ生成 ---
    else:
        st.markdown('<div class="search-heading">✨自由な食材から新作を生成</div>', unsafe_allow_html=True)
        st.write("作りたい料理のイメージ、使いたい食材、味付け、条件などを自由に書いてください。")

        if "generated_recipe" not in st.session_state:
            st.session_state.generated_recipe = None

        input_text = st.text_area(
            "リクエストを入力",
            placeholder="例：なすと厚揚げを使って、夏向けのさっぱりした2人分のおばんざいを作りたい",
            height=140
        )

        if st.button("文章とレシピを生成する", type="primary"):
            if not input_text:
                st.warning("リクエストを入力してください。")
            else:
                with st.spinner("CSV全体の味付け傾向を参考に、新しい文章とレシピを作成しています..."):
                    try:
                        related_context = build_related_recipe_context(df, input_text, limit=20)

                        prompt = f"""
あなたは管理栄養士でやさい料理研究家の大畑ちつるです。
以下のCSV分析データを実際の参考資料として使い、野菜が主役の新作レシピを作ってください。

重要：CSVはレシピ開発の味付けの軸です。頻出調味料をそのまま毎回使うのではなく、
CSV全体にある味付けの幅、組み合わせ方、調理法の傾向を読み取ってください。

{BASE_RECIPE_RULES}

{csv_style_context}

【今回のリクエストに近い過去レシピ 最大20件】
{related_context}

【外部の新しいエッセンスについて】
海外料理やNHKなど信頼できる料理メディアで一般的に知られている食材の組み合わせや調理法を、
新しい発想のヒントとして取り入れてよいです。ただし、このAPI呼び出しではWebページをリアルタイム閲覧していないため、
特定のサイトを今見た、検索した、引用した、とは書かないでください。
外部の発想より、上記CSVから読み取れる味付けの軸を優先してください。

# ユーザーからのリクエスト
{input_text}
"""
                        response = model_instance.generate_content(prompt)
                        st.session_state.generated_recipe = response.text
                        st.success("文章とレシピが完成しました！")

                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

        if st.session_state.generated_recipe:
            st.subheader("📖 生成された文章とレシピ")
            st.markdown(st.session_state.generated_recipe)
            st.divider()
            st.write("### ✍️ 内容を調整する")
            feedback = st.text_input(
                "追加の希望（例：2人分に変更、酸味を強く、材料を減らす、など）",
                key="feedback_input"
            )

            if st.button("この内容で再調整する"):
                if not feedback:
                    st.warning("修正内容を入力してください。")
                else:
                    with st.spinner("内容を調整しています..."):
                        try:
                            edit_prompt = f"""
あなたは料理研究家の大畑ちつるです。
先ほど提案した文章とレシピに対して、ユーザーから修正依頼がありました。

{BASE_RECIPE_RULES}

【修正のルール】
・ユーザーの「追加の希望」を反映してください
・追加希望と矛盾しない部分は、元の文章とレシピをできるだけ維持してください
・顆粒だし、めんつゆ、マヨネーズ、化学調味料は修正後も使わないでください
・不要な「お」は付けないでください

# 元の文章とレシピ
{st.session_state.generated_recipe}

# ユーザーからの追加の希望
{feedback}
"""
                            edit_response = model_instance.generate_content(edit_prompt)
                            st.session_state.generated_recipe = edit_response.text
                            st.rerun()
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")

            st.caption("📋 全文をコピー")
            st.code(st.session_state.generated_recipe, language="text")

            try:
                pdf_bytes = make_recipe_pdf(st.session_state.generated_recipe)
                st.download_button(
                    "📄 PDFでダウンロード",
                    data=pdf_bytes,
                    file_name="generated_recipe.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.warning(f"PDFの作成に失敗しました: {e}")


# --- 4. 実行 ---
if check_password():
    main_app()
else:
    st.stop()
