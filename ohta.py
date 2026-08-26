import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import google.generativeai as genai
import base64
import io
import os
import re
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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

    .app-header {
        margin: 0 0 1.2rem 0;
    }
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
    .app-title-line {
        margin: 0;
    }
    .app-main-title {
        margin: 0.35rem 0 0.45rem 0;
    }
    .app-caption {
        color: #7a7a7a;
        font-size: clamp(12px, 3vw, 15px);
        margin-bottom: 1.2rem;
    }
    .search-heading {
        margin: 1.2rem 0 1rem 0;
    }

    @media (max-width: 480px) {
        .block-container {
            padding-left: 12px !important;
            padding-right: 12px !important;
        }
        .app-header,
        .app-brand-row,
        .app-main-title,
        .app-caption,
        .search-heading {
            margin-left: 0 !important;
        }
        .app-brand-row img {
            width: 34px;
        }
        .app-brand-row {
            gap: 0.4rem;
        }
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
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("RecipeJP", path))
                return "RecipeJP"
            except Exception:
                continue
    return "Helvetica"


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

    model_instance = genai.GenerativeModel('gemini-3-flash-preview')

    @st.cache_data
    def load_data(file_path):
        df = pd.read_csv(file_path)
        df = df[df['Post Type'] == 'recipe'].copy()

        def strip_html(html_str):
            if pd.isna(html_str):
                return ""
            return BeautifulSoup(html_str, "html.parser").get_text(separator=" ").strip()

        df['clean_content'] = df['Content'].apply(strip_html)
        return df

    df = load_data("fa2ac34592382d85a2af03a450f780a4.csv")

    if '季節' in df.columns:
        all_seasons = df['季節'].dropna().unique().tolist()
    else:
        all_seasons = ["春", "夏", "秋", "冬"]

    # 最初に、やりたいことだけ選ぶ
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

        filtered_df = df[df['季節'].isin(selected_seasons)] if selected_seasons else df.iloc[0:0]

        if q:
            keywords = q.split()
            mask = filtered_df['clean_content'].str.contains(keywords[0], na=False, case=False)
            for kw in keywords[1:]:
                mask &= filtered_df['clean_content'].str.contains(kw, na=False, case=False)

            results = filtered_df[mask]
            st.write(f"ヒット数: {len(results)}件")
            for _, row in results.head(10).iterrows():
                with st.expander(f"📖 {row['Title']}"):
                    if pd.notna(row['Image URL']):
                        st.image(row['Image URL'].split('|')[0], width=300)
                    st.markdown(f"**[元記事を見る]({row['Permalink']})**")
                    st.write(row['clean_content'])
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
                with st.spinner("過去のレシピの傾向を参考に、新しい文章とレシピを作成しています..."):
                    try:
                        prompt = f"""
あなたは管理栄養士でやさい料理研究家の大畑ちつるです。

野菜が主役のおばんざいの新作レシピを、
本人がブログで語るような、素材への愛着や食卓の風景を感じる主観的なトーンで書いてください。
味付けや材料選びの傾向は.csvデータの情報を参照して、生成してください。

【文章の雰囲気】
・やさしい温度感
・大阪のおばんざいっぽさ
・季節感がある
・素材の香りや美味しさの描写は入れる
・読んでいて食卓が想像できる文章にする
・あいさつ文は.csvデータを参考に文体を整える
・関西弁は使わず、ですます調
・冒頭は「こんにちは。やさい料理研究家の大畑ちつるです。」で始める

【禁止事項】
・中央卸売市場時代の話は禁止
・昔話は禁止
・自分語りは禁止
・「淡口しょうゆ」は禁止。必ず「薄口しょうゆ」を使う
・AIっぽい説明は禁止
・「〜が特徴です」「〜を採用しました」は禁止

【文章量】
・冒頭文は3〜5段落ほど
・短すぎず、読みものとして楽しめる長さにする
・ただし長編エッセイにはしない

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
・料理初心者でも作れる説明にする

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

【修正のルール】
・ユーザーの「追加の希望」を反映してください。
・それ以外の部分は、元の文章とレシピから絶対に変えないでください。
・引き続き、大畑ちつる本人のトーンを維持してください。

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
