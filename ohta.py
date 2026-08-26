import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import google.generativeai as genai
import base64

# --- 1. ページ設定 ---
st.set_page_config(
    page_title="レシピ検索アプリ",
    page_icon="logo.png",
    layout="wide"
)

# --- 2. 認証機能（シークレット管理に対応） ---
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

# --- 3. メイン処理 ---
def main_app():
    def get_image_base64(file_path):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            return base64.b64encode(data).decode()
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
    else:
        st.markdown('<link rel="apple-touch-icon" href="logo.png">', unsafe_allow_html=True)

    # 右上ロゴ＋テキストタイトル
    header_left, header_right = st.columns([8, 1])
    with header_left:
        st.markdown("## やさい料理研究家 大畑ちつる")
        st.markdown("# レシピリサーチ＆レシピメーカー")
        st.caption("日々の献立作りをサポートする、プロの野菜レシピ検索ツールです。")
    with header_right:
        st.image("logo.png", width=85)

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

    mode_options = ["過去レシピを検索", "自由な食材から新作を生成"]

    # サイドバーとメイン画面の選択内容を同期
    if "sidebar_seasons" not in st.session_state:
        st.session_state.sidebar_seasons = all_seasons
    if "main_seasons" not in st.session_state:
        st.session_state.main_seasons = list(st.session_state.sidebar_seasons)
    if "sidebar_mode" not in st.session_state:
        st.session_state.sidebar_mode = mode_options[0]
    if "main_mode" not in st.session_state:
        st.session_state.main_mode = st.session_state.sidebar_mode

    def sync_seasons_from_sidebar():
        st.session_state.main_seasons = list(st.session_state.sidebar_seasons)

    def sync_seasons_from_main():
        st.session_state.sidebar_seasons = list(st.session_state.main_seasons)

    def sync_mode_from_sidebar():
        st.session_state.main_mode = st.session_state.sidebar_mode

    def sync_mode_from_main():
        st.session_state.sidebar_mode = st.session_state.main_mode

    # サイドバー
    st.sidebar.title("メニュー")
    st.sidebar.markdown("### 🔍 レシピを絞り込む")

    st.sidebar.multiselect(
        "季節・旬を選択",
        options=all_seasons,
        key="sidebar_seasons",
        on_change=sync_seasons_from_sidebar
    )

    st.sidebar.radio(
        "機能を選択",
        mode_options,
        key="sidebar_mode",
        on_change=sync_mode_from_sidebar
    )

    # メイン画面
    mode = st.session_state.main_mode

    if mode == "過去レシピを検索":
        st.title("🔍 過去レシピ検索")
        q = st.text_input("キーワードを入力（食材や料理名）", placeholder="例：なす 豚肉")

        st.markdown("### 季節・旬を選択")
        st.multiselect(
            "季節・旬",
            options=all_seasons,
            key="main_seasons",
            on_change=sync_seasons_from_main,
            label_visibility="collapsed"
        )

        st.markdown("### 機能を選択")
        st.radio(
            "機能",
            mode_options,
            key="main_mode",
            on_change=sync_mode_from_main,
            label_visibility="collapsed",
            horizontal=True
        )

        selected_seasons = st.session_state.main_seasons
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

    else:
        st.title("✨ 自由食材で新作生成")
        st.write("手元にある食材や、使いたい調味料を自由に入力してください。")

        st.markdown("### 季節・旬を選択")
        st.multiselect(
            "季節・旬",
            options=all_seasons,
            key="main_seasons",
            on_change=sync_seasons_from_main,
            label_visibility="collapsed"
        )

        st.markdown("### 機能を選択")
        st.radio(
            "機能",
            mode_options,
            key="main_mode",
            on_change=sync_mode_from_main,
            label_visibility="collapsed",
            horizontal=True
        )

        if "generated_recipe" not in st.session_state:
            st.session_state.generated_recipe = None

        input_text = st.text_area("使いたい食材・条件を入力", placeholder="例：なす、厚揚げ、少しピリ辛にしたい")

        if st.button("大畑ちつるスタイルでレシピを考案"):
            if not input_text:
                st.warning("食材を入力してください。")
            else:
                with st.spinner("大畑ちつるの過去の味付けを分析して考案中..."):
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
以下の順番で必ず書く

1. 挨拶
2. 季節や素材についての短い導入
3. レシピタイトル
4. 材料
5. 作り方
6. 食べた時の魅力やおすすめの食べ方

【作り方のルール】
・必ず番号をつける
・各工程に見出しをつける

例：
1. 素材を切る
2. 鮭を焼く
3. 味を絡める

・工程ごとに1〜3文で丁寧に説明する
・料理初心者でも作れる説明にする

# ユーザーからのリクエスト（食材・条件）
{input_text}
"""
                        response = model_instance.generate_content(prompt)
                        st.session_state.generated_recipe = response.text
                        st.success("新作レシピ案が完成しました！")

                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

        if st.session_state.generated_recipe:
            st.subheader("📖 大畑ちつるの新作レシピ")
            st.markdown(st.session_state.generated_recipe)

            st.divider()

            st.write("### ✍️ レシピを調整する")
            feedback = st.text_input("追加の希望（例：2人分に変更、もう少し酸っぱく、等）", key="feedback_input")

            if st.button("この内容で再調整する"):
                if not feedback:
                    st.warning("修正内容を入力してください。")
                else:
                    with st.spinner("レシピを微調整しています..."):
                        try:
                            edit_prompt = f"""
あなたは料理研究家の大畑ちつるです。
先ほど提案したレシピに対して、ユーザーから修正依頼がありました。

【修正のルール】
・ユーザーの「追加の希望」を反映してください。
・**それ以外の部分は、元のレシピから絶対に変えないでください。** 構成や語り口を維持したまま、必要な箇所だけを書き換えてください。
・引き続き、大畑ちつる本人のトーンを維持してください。

# 元のレシピ
{st.session_state.generated_recipe}

# ユーザーからの追加の希望
{feedback}
"""
                            edit_response = model_instance.generate_content(edit_prompt)
                            st.session_state.generated_recipe = edit_response.text
                            st.rerun()

                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")

            st.caption("📋 レシピ全文をコピー")
            st.code(st.session_state.generated_recipe, language="text")

# --- 4. 実行のトリガー ---
if check_password():
    main_app()
else:
    st.stop()
