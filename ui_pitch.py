"""Dibuja el 11 titular sobre un campo de fútbol (estilo "Mi alineación" de Biwenger)."""

import streamlit as st

ROW_ORDER = [("DL", 13), ("MC", 40), ("DF", 67), ("PT", 90)]  # (posición, % desde arriba)

BADGE_COLOR = {"PT": "#c1893f", "DF": "#3d75ad", "MC": "#7565b0", "DL": "#a3505f"}
BADGE_TEXT_COLOR = {"PT": "#ffffff", "DF": "#ffffff", "MC": "#ffffff", "DL": "#ffffff"}


def render_pitch(starters):
    by_position = {"PT": [], "DF": [], "MC": [], "DL": []}
    for p in starters:
        by_position.setdefault(p["position"], []).append(p)

    players_html = []
    for pos, top in ROW_ORDER:
        group = by_position.get(pos, [])
        n = len(group)
        for i, p in enumerate(group):
            left = (i + 1) / (n + 1) * 100
            if p.get("empty"):
                players_html.append(
                    f'<div class="bw-player" style="top:{top}%; left:{left}%;">'
                    f'<div class="bw-badge bw-badge-empty">?</div>'
                    f'<div class="bw-pname bw-pname-empty">Vacío ({pos})</div>'
                    f"</div>"
                )
                continue
            short_name = p["name"] if len(p["name"]) <= 14 else p["name"][:13] + "…"
            players_html.append(
                f'<div class="bw-player" style="top:{top}%; left:{left}%;">'
                f'<div class="bw-badge" style="background:{BADGE_COLOR[pos]}; color:{BADGE_TEXT_COLOR[pos]};">{pos}</div>'
                f'<div class="bw-pname">{short_name}</div>'
                f'<div class="bw-pscore">{p["score"]}</div>'
                f"</div>"
            )

    st.markdown(
        f"""
        <style>
        .bw-pitch {{
            position: relative;
            width: 100%;
            max-width: 480px;
            margin: 0 auto 1.2rem auto;
            aspect-ratio: 3 / 4;
            background:
                repeating-linear-gradient(
                    to bottom,
                    #2f7a4f 0, #2f7a4f 10%,
                    #35854f 10%, #35854f 20%
                );
            border-radius: 12px;
            border: 2px solid rgba(255, 255, 255, 0.35);
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
        }}
        .bw-pitch-halfway {{
            position: absolute; top: 50%; left: 0; right: 0; height: 2px;
            background: rgba(255, 255, 255, 0.5);
        }}
        .bw-pitch-circle {{
            position: absolute; top: 50%; left: 50%; width: 70px; height: 70px;
            border: 2px solid rgba(255, 255, 255, 0.5); border-radius: 50%;
            transform: translate(-50%, -50%);
        }}
        .bw-pitch-box-top {{
            position: absolute; top: 0; left: 25%; width: 50%; height: 12%;
            border: 2px solid rgba(255, 255, 255, 0.5); border-top: none;
        }}
        .bw-pitch-box-bottom {{
            position: absolute; bottom: 0; left: 25%; width: 50%; height: 12%;
            border: 2px solid rgba(255, 255, 255, 0.5); border-bottom: none;
        }}
        .bw-player {{
            position: absolute;
            transform: translate(-50%, -50%);
            display: flex; flex-direction: column; align-items: center;
            width: 78px;
        }}
        .bw-badge {{
            width: 40px; height: 40px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 0.7rem; font-weight: 700; color: #ffffff;
            border: 2px solid rgba(255, 255, 255, 0.85);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
        }}
        .bw-pname {{
            margin-top: 4px; font-size: 0.68rem; font-weight: 700; color: #ffffff;
            text-shadow: 0 1px 3px rgba(0, 0, 0, 0.7);
            text-align: center; line-height: 1.15;
            max-width: 78px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .bw-pscore {{
            font-size: 0.62rem; color: #e6f3ea; opacity: 0.9;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
        }}
        .bw-badge-empty {{
            background: rgba(255, 255, 255, 0.12);
            border: 2px dashed rgba(255, 255, 255, 0.75);
            color: rgba(255, 255, 255, 0.85);
        }}
        .bw-pname-empty {{ opacity: 0.75; font-weight: 600; }}

        /* Móvil: filas de hasta 5 jugadores necesitan insignias y nombres más compactos */
        @media (max-width: 480px) {{
            .bw-player {{ width: 58px; }}
            .bw-badge {{ width: 30px; height: 30px; font-size: 0.6rem; border-width: 1.5px; }}
            .bw-pname {{ font-size: 0.58rem; max-width: 58px; margin-top: 2px; }}
            .bw-pscore {{ font-size: 0.55rem; }}
        }}
        </style>
        <div class="bw-pitch">
            <div class="bw-pitch-halfway"></div>
            <div class="bw-pitch-circle"></div>
            <div class="bw-pitch-box-top"></div>
            <div class="bw-pitch-box-bottom"></div>
            {"".join(players_html)}
        </div>
        """,
        unsafe_allow_html=True,
    )
