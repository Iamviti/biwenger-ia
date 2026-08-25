"""
Estilo compartido por cada vista de Biwenger IA.

Usa las variables CSS que Streamlit ya expone (--text-color, --background-color,
--secondary-background-color) en vez de colores fijos, para que se adapten solas al
modo claro/oscuro que el usuario elija en el menú ⋮ → Settings → Theme (o al de su
sistema operativo) sin necesidad de mantener dos paletas por separado.

Acento de marca: paleta "Minty Fresh" de Figma (#98FBCB, #BFFFED, #7FCFA8, #558B71),
aplicada a cabeceras, pestañas, botones, expanders y métricas de toda la web.
"""

import streamlit as st

MINT_PALE = "#BFFFED"
MINT_LIGHT = "#98FBCB"
MINT = "#7FCFA8"
MINT_DARK = "#558B71"


def inject_style():
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 3.5rem; padding-bottom: 2rem; max-width: 1200px; }}

        .bw-title {{
            font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 0;
            color: var(--text-color);
            border-left: 5px solid {MINT}; padding-left: 12px;
        }}
        .bw-subtitle {{ color: var(--text-color); opacity: 0.65; font-size: 0.9rem; margin-top: 6px; margin-bottom: 1.4rem; padding-left: 17px; }}

        div[data-testid="stMetric"] {{
            background: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-top: 3px solid {MINT};
            border-radius: 8px;
            padding: 12px 16px;
        }}
        div[data-testid="stMetricLabel"] {{ opacity: 0.7; font-size: 0.85rem; }}

        div[data-testid="stExpander"] {{
            border: 1px solid rgba(128, 128, 128, 0.25) !important;
            border-top: 3px solid {MINT} !important;
            border-radius: 8px !important;
            background: var(--secondary-background-color);
            margin-bottom: 14px;
            box-shadow: none;
            overflow: hidden;
        }}
        div[data-testid="stExpander"] summary {{ font-size: 1rem; font-weight: 600; padding: 6px 4px; }}

        div[data-testid="stDataFrame"] {{ border-radius: 6px; overflow: hidden; }}

        /* Pestañas (st.tabs) */
        .stTabs [data-baseweb="tab-highlight"] {{ background-color: {MINT} !important; }}
        .stTabs [data-baseweb="tab"][aria-selected="true"] {{ color: {MINT_DARK} !important; }}
        .stTabs [data-baseweb="tab"]:hover {{ color: {MINT_DARK} !important; }}

        /* Botón de refrescar — icono tipo "material", sin relleno */
        .stButton button, button[kind="primary"], button[kind="primaryFormSubmit"] {{
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #ffffff !important;
            border-radius: 50% !important;
        }}
        .stButton button:hover, button[kind="primary"]:hover {{
            background-color: rgba(255, 255, 255, 0.12) !important;
        }}

        /* Estado vacío (sin datos todavía) */
        .bw-empty {{
            text-align: center;
            padding: 56px 24px;
            background: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-top: 3px solid {MINT};
            border-radius: 8px;
            margin: 12px 0 24px 0;
        }}
        .bw-empty-icon {{ font-size: 2.6rem; margin-bottom: 14px; }}
        .bw-empty-text {{ font-size: 1.05rem; font-weight: 700; color: var(--text-color); margin-bottom: 6px; }}
        .bw-empty-hint {{ font-size: 0.9rem; color: var(--text-color); opacity: 0.65; }}

        /* Radio y checkbox seleccionados (st.radio, filtros) */
        div[data-testid="stRadio"] label[data-baseweb="radio"] div:first-child {{
            border-color: {MINT_DARK} !important;
        }}
        div[data-testid="stRadio"] label[data-baseweb="radio"] div:first-child div {{
            background-color: {MINT_DARK} !important;
        }}

        /* Enlaces de texto */
        a {{ color: {MINT_DARK}; }}

        /* Barra de progreso / spinner */
        div[data-testid="stSpinner"] svg {{ color: {MINT} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def money(value):
    """Formatea una cantidad con puntos como separador de miles (2.000.000, no 2,000,000)."""
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.0f}".replace(",", ".")


def empty_state(message, hint="Pulsa 🔄 arriba a la derecha para traer tus datos de Biwenger y SofaScore."):
    """Aviso de "todavía no hay datos" con más presencia visual que un st.info suelto."""
    st.markdown(
        f"""
        <div class="bw-empty">
            <div class="bw-empty-icon">📭</div>
            <div class="bw-empty-text">{message}</div>
            <div class="bw-empty-hint">{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def header(title, subtitle=None):
    col_title, col_refresh = st.columns([9, 1], vertical_alignment="center")
    with col_title:
        st.markdown(f'<div class="bw-title">{title}</div>', unsafe_allow_html=True)
    with col_refresh:
        refresh_clicked = st.button("🔄", help="Actualizar datos desde Biwenger y SofaScore", key="bw_refresh_btn")
    if subtitle:
        st.markdown(f'<div class="bw-subtitle">{subtitle}</div>', unsafe_allow_html=True)

    # Fuera de la columna estrecha del botón, a todo el ancho, para que el log no salga
    # apretado en una franja vertical.
    if refresh_clicked:
        from scripts.fetch_data import main as fetch_all_data

        with st.status("Actualizando datos...", expanded=True) as status:
            try:
                fetch_all_data(log=status.write)
                status.update(label="Datos actualizados", state="complete")
            except Exception as e:
                status.update(label=f"Fallo al actualizar: {e}", state="error")
        st.rerun()
