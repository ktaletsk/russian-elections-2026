import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Выборы в Госдуму-2026: что говорят протоколы участков

    Отчёт о голосовании по партийным спискам на выборах в Государственную думу 18–20 сентября 2026 года,
    построенный по протоколам участковых избирательных комиссий (УИК).

    Сначала — итоги: партии, явка, электронное голосование, регионы. Затем — то, чего в официальных
    итогах не видно: как голоса распределены по участкам и какие статистические аномалии есть в этом
    распределении по сравнению со всеми федеральными выборами начиная с 2000 года.

    > ⚠️ Данные 2026 года предварительные: на момент снимка ЦИК опубликовал протоколы не всех участков
    > (нет Ленинградской области и оккупированных территорий).
    """)
    return


@app.cell
def imports():
    import io
    import json
    import time
    import zipfile
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests

    return Path, json, mo, np, pd, plt, requests


@app.cell
def config(Path):
    # Протоколы 2000–2024: репозиторий Д. Кобака, закреплён на конкретном коммите
    KOBAK_COMMIT = "bbcc7ab4766935bbcab063b8a74d9ac55ec929eb"
    KOBAK_RAW = f"https://raw.githubusercontent.com/dkobak/elections/{KOBAK_COMMIT}/data/"
    # Протоколы 2026: статический CDN проекта neshodilina (зеркало сводных таблиц ЦИК)
    NESHODILINA = "https://pub-9b41d66c14bb4c2fa747a03654838e30.r2.dev/data/"

    DATA_DIR = Path("data")
    DATA_DIR.mkdir(exist_ok=True)

    DUMA_YEARS = [2003, 2007, 2011, 2016, 2021, 2026]
    ALL_YEARS = [2000, 2003, 2004, 2007, 2008, 2011, 2012, 2016, 2018, 2021, 2024, 2026]
    PRESIDENTIAL = {2000, 2004, 2008, 2012, 2018, 2024}
    LEADER_NAME = {2000: "Путин", 2004: "Путин", 2008: "Медведев", 2012: "Путин",
                   2018: "Путин", 2024: "Путин"}  # в думских выборах лидер — «Единая Россия»
    return (
        ALL_YEARS,
        DATA_DIR,
        DUMA_YEARS,
        KOBAK_RAW,
        LEADER_NAME,
        NESHODILINA,
        PRESIDENTIAL,
    )


@app.cell
def load_historical(DATA_DIR, KOBAK_RAW, pd, requests):
    def _pick(table, include, exclude=()):
        """Колонки протокола, в названии которых есть любая из подстрок include."""
        return [c for c in table.columns
                if any(s in c for s in include) and not any(s in c for s in exclude)]


    def load_historical(year):
        """Протоколы УИК 2000–2024 → стандартная таблица (логика колонок как в dkobak/elections)."""
        path = DATA_DIR / f"{year}.csv.zip"
        if not path.exists():
            path.write_bytes(requests.get(KOBAK_RAW + f"{year}.csv.zip", timeout=120).content)
        table = pd.read_csv(path)

        leader = _pick(table, ["ПУТИН", "Путин", "Единая Россия", "ЕДИНАЯ РОССИЯ", "Медведев"])
        voters = _pick(table, ["Число избирателей, включенных", "Число избирателей, внесенных"])
        given = _pick(table, ["бюллетеней, выданных"])  # досрочно + в помещении + вне помещения
        received = _pick(table, ["действительных", "недействительных"], exclude=["отметок"])
        assert len(leader) == 1 and len(voters) == 1 and len(given) == 3 and len(received) == 2, year

        out = pd.DataFrame({
            "region": table["region"].values,
            "tik": table["tik"].values,
            "uik": table["uik"].values,
            "voters": table[voters[0]].values,
            "given": table[given].sum(axis=1).values,
            "received": table[received].sum(axis=1).values,
            "leader": table[leader[0]].values,
        })
        return out.dropna(subset=["leader"]).astype(
            {"voters": int, "given": int, "received": int, "leader": int}
        )

    return (load_historical,)


@app.cell
def load_2026(DATA_DIR, NESHODILINA, json, pd, requests):
    def load_2026(refresh=False):
        """Протоколы УИК 2026 (федеральный список) → стандартная таблица + метаданные снимка.

        Скачанный снимок сохраняется в data/, чтобы результаты были воспроизводимы:
        источник обновляется каждые ~15 минут, пока ЦИК догружает протоколы.
        """
        snap, meta_path = DATA_DIR / "2026_federal.parquet", DATA_DIR / "2026_meta.json"
        if refresh or not snap.exists():
            meta = requests.get(NESHODILINA + "meta.json", timeout=60).json()
            rows = []
            for r in meta["regions"]:
                if r["uiks"] == 0:
                    continue  # регион без опубликованных протоколов
                reg = requests.get(NESHODILINA + f"fed/r{r['id']}.json", timeout=120).json()
                for u in reg["uiks"]:
                    row = {"region": reg["region"], "tik": u["tik"], "uik": u["name"]}
                    row.update({f"line{i + 1}": v for i, v in enumerate(u["protocol"])})
                    row.update(dict(zip(reg["parties"], u["votes"])))
                    rows.append(row)
            pd.DataFrame(rows).to_parquet(snap)
            # ДЭГ публикуется не по участкам, а по округам — берём сводку по регионам
            regions_json = requests.get(NESHODILINA + "regions.json", timeout=60).json()
            meta_path.write_text(json.dumps(
                {"generated_at": meta["generated_at"], "stats": meta["stats"], "regions": regions_json},
                ensure_ascii=False))
        raw = pd.read_parquet(snap)
        meta = json.loads(meta_path.read_text())

        er = [c for c in raw.columns if "ЕДИНАЯ РОССИЯ" in c]
        assert len(er) == 1
        out = pd.DataFrame({
            "region": raw["region"].values,
            "tik": raw["tik"].values,
            "uik": raw["uik"].values,
            "voters": raw["line1"].values,  # число избирателей в списке
            "given": (raw["line3"] + raw["line4"] + raw["line5"]).values,  # выданные бюллетени
            "received": (raw["line9"] + raw["line10"]).values,  # недействительные + действительные
            "leader": raw[er[0]].values,
        })
        return out.dropna(subset=["leader"]).astype(
            {"voters": int, "given": int, "received": int, "leader": int}
        ), meta


    return (load_2026,)


@app.cell(hide_code=True)
def refresh_button(mo):
    refresh_2026 = mo.ui.run_button(label="⟳ Скачать свежий снимок 2026 года")
    refresh_2026
    return (refresh_2026,)


@app.cell
def elections(ALL_YEARS, load_2026, load_historical, pd, refresh_2026):
    def is_deg_pseudo(df, year):
        """Псевдо-УИКи дистанционного электронного голосования (есть в данных 2021 года)."""
        deg = df["tik"].astype(str).str.contains("Дистанционное электронное")
        if year == 2021:
            num = pd.to_numeric(df["uik"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
            deg |= (df["region"] == "город Москва") & num.between(5001, 5015)
        return deg


    def _prepare(df, year):
        df = df.assign(year=year, deg=is_deg_pseudo(df, year))
        df = df[~df["deg"] & (df["voters"] > 0)].copy()
        df["turnout"] = 100 * df["given"] / df["voters"]
        df["result"] = 100 * df["leader"] / df["received"].where(df["received"] > 0)
        return df


    table_2026, meta_2026 = load_2026(refresh=refresh_2026.value)
    elections = {y: _prepare(load_historical(y), y) for y in ALL_YEARS if y < 2026}
    elections[2026] = _prepare(table_2026, 2026)
    return elections, is_deg_pseudo, meta_2026, table_2026


@app.cell(hide_code=True)
def data_md(elections, meta_2026, mo):
    mo.md(
        f"""
    ## Данные

    | Выборы | Что это | Откуда |
    |---|---|---|
    | 2000–2021 | протоколы УИК всех федеральных выборов, собранные с izbirkom.ru Сергеем Шпилькиным | [github.com/dkobak/elections](https://github.com/dkobak/elections/tree/master/data) |
    | 2024 | протоколы УИК президентских выборов (сбор — Иван Шукшин) | там же |
    | 2026 | протоколы УИК из публичных сводных таблиц ЦИК | [neshodilina.netlify.app/api](https://neshodilina.netlify.app/api) |

    Снимок 2026 года: **{meta_2026["generated_at"].replace("T", " ")}**, УИКов с протоколом федерального списка —
    **{len(elections[2026]):,}** из {meta_2026["stats"]["total_uiks"]:,}. Итоги ДЭГ (дистанционного электронного
    голосования) ЦИК публикует не по участкам, а по одномандатным округам, поэтому в анализе участков
    используются только «бумажные» УИКи — и в 2026, и в прошлые годы.
    """.replace(",", " ")
    )
    return


@app.cell
def plot_helpers(np, plt):
    BG = "#F0EEE6"  # тёплый бумажный фон графиков
    C_OLD, C_NEW = "#555555", "#B8995E"
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    })


    def jittered(df, seed=42, for_histogram=False):
        """Явка и результат по УИКам с шумом U(-0.5, 0.5) в числителе, как у Кобака:
        убирает артефакты деления на маленьких участках, не размывая целые проценты.

        Для диаграмм рассеяния оставляем УИКи со 100% явкой и прижимаем точки к [0, 100];
        для гистограмм берём критерий Кобака (выдано < избирателей) и не обрезаем значения.
        """
        rng = np.random.default_rng(seed)
        full = df["given"] < df["voters"] if for_histogram else df["given"] <= df["voters"]
        d = df[(df["received"] > 0) & full]
        x = 100 * (d["given"] + rng.random(len(d)) - 0.5) / d["voters"]
        y = 100 * (d["leader"] + rng.random(len(d)) - 0.5) / d["received"]
        if not for_histogram:
            x, y = x.clip(0, 100), y.clip(0, 100)
        return d.assign(x=x, y=y)


    def comet_axes(ax, title=None, ylabel="Результат «Единой России», %"):
        ax.set_xlim(0, 101)
        ax.set_ylim(0, 101)
        ax.set_aspect("equal")
        ax.set_xticks(range(0, 101, 20))
        ax.set_yticks(range(0, 101, 20))
        ax.set_xlabel("Явка, %")
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title, loc="left", fontweight="bold")

    return C_NEW, C_OLD, comet_axes, jittered


@app.cell
def results(
    DATA_DIR,
    is_deg_pseudo,
    load_historical,
    meta_2026,
    np,
    pd,
    table_2026,
):
    PARTY_SHORT = [  # подстрока официального названия → короткое имя (порядок важен)
        ("ЕДИНАЯ РОССИЯ", "Единая Россия"),
        ("КОММУНИСТЫ РОССИИ", "Коммунисты России"),
        ("КОММУНИСТИЧЕСКАЯ ПАРТИЯ РОССИЙСКОЙ ФЕДЕРАЦИИ", "КПРФ"),
        ("ЛДПР", "ЛДПР"),
        ("НОВЫЕ ЛЮДИ", "Новые люди"),
        ("СПРАВЕДЛИВАЯ РОССИЯ", "Справедливая Россия"),
        ("ПЕНСИОНЕРОВ", "Партия пенсионеров"),
        ("ЗЕЛЁНЫЕ", "Зелёные"),
        ("ЗЕЛЕНАЯ АЛЬТЕРНАТИВА", "Зелёная альтернатива"),
        ("РОДИНА", "Родина"),
        ("ЯБЛОКО", "Яблоко"),
        ("ПАРТИЯ РОСТА", "Партия Роста"),
        ("СВОБОДЫ И СПРАВЕДЛИВОСТИ", "Партия свободы и справедливости"),
        ("Гражданская Платформа", "Гражданская платформа"),
        ("Партия прямой демократии", "Партия прямой демократии"),
    ]
    INVALID, VALID = "Число недействительных избирательных бюллетеней", "Число действительных избирательных бюллетеней"


    def short_party(name):
        return next(short for key, short in PARTY_SHORT if key in name)


    def party_results(year):
        """Голоса за партии на участках, в ДЭГ и всего.

        Проценты — от всех бюллетеней в ящиках (действительные + недействительные), как считает ЦИК.
        """
        if year == 2021:
            raw = pd.read_csv(DATA_DIR / "2021.csv.zip")
            cols = [c for c in raw.columns if c.split(".")[0].isdigit()]
            deg = is_deg_pseudo(raw, 2021)
            paper, online = raw.loc[~deg, cols].sum(), raw.loc[deg, cols].sum()
            ballots_paper = raw.loc[~deg, [INVALID, VALID]].to_numpy().sum()
            ballots_deg = raw.loc[deg, [INVALID, VALID]].to_numpy().sum()
        else:
            raw = pd.read_parquet(DATA_DIR / "2026_federal.parquet")
            regions = meta_2026["regions"]["regions"]
            parties = meta_2026["regions"]["parties"]
            paper = raw[parties].sum()
            online = pd.Series(np.sum([r["deg"]["f"] for r in regions], axis=0), index=parties)
            ballots_paper = (raw["line9"] + raw["line10"]).sum()
            ballots_deg = sum(r["deg"]["fp"][8] + r["deg"]["fp"][9] for r in regions)
        df = pd.DataFrame({"Партия": [short_party(c) for c in paper.index],
                           "На участках": paper.to_numpy(), "ДЭГ": online.to_numpy()})
        df["Всего"] = df["На участках"] + df["ДЭГ"]
        df["%"] = (100 * df["Всего"] / (ballots_paper + ballots_deg)).round(2)
        df["% на участках"] = (100 * df["На участках"] / ballots_paper).round(2)
        df["% в ДЭГ"] = (100 * df["ДЭГ"] / ballots_deg).round(2)
        return df.sort_values("Всего", ascending=False, ignore_index=True)


    def turnout_totals(year):
        """Явка с учётом ДЭГ и доля ДЭГ среди выданных бюллетеней."""
        if year == 2021:
            raw = load_historical(2021)
            deg = is_deg_pseudo(raw, 2021)
            voters, given, given_deg = raw["voters"].sum(), raw["given"].sum(), raw.loc[deg, "given"].sum()
        else:
            regions = meta_2026["regions"]["regions"]
            voters = table_2026["voters"].sum() + sum(r["deg"]["fp"][0] for r in regions)
            given_deg = sum(r["deg"]["fp"][3] for r in regions)
            given = table_2026["given"].sum() + given_deg
        return {"явка": 100 * given / voters, "доля ДЭГ": 100 * given_deg / given, "избирателей": voters}


    parties = {y: party_results(y) for y in (2021, 2026)}
    turnout = {y: turnout_totals(y) for y in (2021, 2026)}
    return parties, turnout


@app.cell(hide_code=True)
def headline(elections, mo, parties, turnout):
    def _stat(label, v26, v21):
        d = v26 - v21
        return mo.stat(value=f"{v26:.1f}%", label=label, caption=f"{d:+.1f} п.п. к 2021",
                       direction="increase" if d > 0 else "decrease", bordered=True)


    _p26, _p21 = (parties[y].set_index("Партия")["%"] for y in (2026, 2021))
    mo.vstack([
        mo.md("## Главное"),
        mo.hstack(
            [_stat("Явка", turnout[2026]["явка"], turnout[2021]["явка"])]
            + [_stat(p, _p26[p], _p21[p]) for p in ["Единая Россия", "КПРФ", "ЛДПР", "Новые люди", "Справедливая Россия"]],
            wrap=True, justify="start",
        ),
        mo.md(f"""Предварительные итоги по {len(elections[2026]):,} участкам и ДЭГ. Электронно проголосовали
    **{turnout[2026]["доля ДЭГ"]:.1f}%** избирателей, пришедших на выборы (в 2021 году — {turnout[2021]["доля ДЭГ"]:.1f}%).""".replace(",", " ")),
    ])
    return


@app.cell(hide_code=True)
def parties_md(mo):
    mo.md(r"""
    ## 1. Итоги по партиям

    Результаты голосования по федеральному списку с учётом ДЭГ. Пунктир — пятипроцентный барьер,
    который нужно преодолеть, чтобы получить места по партийным спискам.
    """)
    return


@app.cell
def fig_parties(C_NEW, C_OLD, mo, np, parties, plt):
    def _fig_parties():
        t = parties[2026][["Партия", "%"]].merge(parties[2021][["Партия", "%"]], on="Партия", how="outer",
                                               suffixes=(" 2026", " 2021")).fillna(0)
        t = t[t[["% 2026", "% 2021"]].max(axis=1) >= 0.5].sort_values("% 2026")
        y = np.arange(len(t))
        fig, ax = plt.subplots(figsize=(11, 0.5 * len(t) + 1.2), layout="constrained")
        ax.barh(y + 0.2, t["% 2021"], height=0.38, color=C_OLD, label="2021")
        ax.barh(y - 0.2, t["% 2026"], height=0.38, color=C_NEW, label="2026")
        for yi, v in zip(y, t["% 2026"]):
            ax.text(v + 0.5, yi - 0.2, f"{v:.1f}%" if v > 0 else "не участвовала", va="center", fontsize=9,
                    fontweight="bold" if v > 0 else "normal", color="k" if v > 0 else "#888888")
        for yi, v in zip(y, t["% 2021"]):
            if v > 0:
                ax.text(v + 0.5, yi + 0.2, f"{v:.1f}%", va="center", fontsize=8, color=C_OLD)
        ax.axvline(5, color="#999999", ls="--", lw=1)
        ax.set_yticks(y, t["Партия"])
        ax.set_xlabel("% от бюллетеней в ящиках")
        ax.legend(frameon=False, loc="lower right")
        ax.set_title("Результаты партий, 2021 и 2026", loc="left", fontweight="bold", fontsize=13)
        return fig


    mo.vstack([
        _fig_parties(),
        mo.accordion({"Таблица: голоса на участках и в ДЭГ, 2026": mo.ui.table(parties[2026], selection=None)}),
    ])
    return


@app.cell(hide_code=True)
def deg_md(deg_table, mo, turnout):
    mo.md(f"""
    ## 2. Явка и электронное голосование

    Явка с учётом ДЭГ — **{turnout[2026]["явка"]:.1f}%** (в 2021 году — {turnout[2021]["явка"]:.1f}%).
    ДЭГ проводилось в **{len(deg_table)}** регионах; в Москве электронно проголосовали
    **{deg_table.set_index("Регион").loc["город Москва", "Доля ДЭГ, %"]}%** избирателей, в остальных регионах — от
    {deg_table["Доля ДЭГ, %"].min()}% до {deg_table.query("Регион != 'город Москва'")["Доля ДЭГ, %"].max()}%.

    Справа — результат «Единой России» на участках и в ДЭГ того же региона. ЦИК публикует итоги ДЭГ
    по одномандатным округам, где электронное голосование было разрешено, так что это сравнение
    по региону в целом, а не по одним и тем же избирателям.
    """)
    return


@app.cell
def deg_tables(meta_2026, pd):
    ER_INDEX = next(i for i, p in enumerate(meta_2026["regions"]["parties"]) if "ЕДИНАЯ РОССИЯ" in p)

    _rows = []
    for _r in meta_2026["regions"]["regions"]:
        _deg = _r["deg"]["fp"][3]  # бюллетени, выданные в ДЭГ (строка 4 протокола)
        if _deg == 0:
            continue
        _paper = _r["proto"][2] + _r["proto"][3] + _r["proto"][4]
        _rows.append({
            "Регион": _r["name"], "Бюллетеней в ДЭГ": _deg, "Бюллетеней на участках": _paper,
            "Доля ДЭГ, %": round(100 * _deg / (_deg + _paper), 1),
            "ЕР на участках, %": round(100 * _r["fed"][ER_INDEX] / (_r["proto"][8] + _r["proto"][9]), 1),
            "ЕР в ДЭГ, %": round(100 * _r["deg"]["f"][ER_INDEX] / (_r["deg"]["fp"][8] + _r["deg"]["fp"][9]), 1),
        })
    deg_table = pd.DataFrame(_rows).sort_values("Доля ДЭГ, %", ascending=False, ignore_index=True)
    return (deg_table,)


@app.cell
def fig_deg(C_OLD, deg_table, mo, np, plt):
    def _fig_deg():
        t = deg_table.iloc[::-1]
        y = np.arange(len(t))
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 0.28 * len(t) + 1.5), sharey=True, layout="constrained")
        a1.barh(y, t["Доля ДЭГ, %"], color="#5B84D6")
        for yi, v in zip(y, t["Доля ДЭГ, %"]):
            a1.text(v + 1, yi, f"{v:.0f}%", va="center", fontsize=8)
        a1.set_yticks(y, t["Регион"], fontsize=8)
        a1.set_title("Доля ДЭГ среди выданных бюллетеней", loc="left", fontweight="bold")
        a1.set_xlim(0, 100)
        a2.hlines(y, t["ЕР на участках, %"], t["ЕР в ДЭГ, %"], color="#BBBBBB", lw=2)
        a2.scatter(t["ЕР на участках, %"], y, color=C_OLD, s=18, label="на участках", zorder=3)
        a2.scatter(t["ЕР в ДЭГ, %"], y, color="#5B84D6", s=18, label="в ДЭГ", zorder=3)
        a2.set_title("Результат «Единой России», %", loc="left", fontweight="bold")
        a2.legend(frameon=False, loc="lower right")
        a2.set_xlim(0, 100)
        return fig


    mo.vstack([_fig_deg(), mo.accordion({"Таблица по регионам": mo.ui.table(deg_table, selection=None)})])
    return


@app.cell(hide_code=True)
def regions_overview_md(MIN_UIKS, mo, region_overview):
    def _names(t):
        return ", ".join(f"{r['Регион'].replace('город ', '')} ({r['Δ ЕР, п.п.']:+.0f})" for _, r in t.iterrows())


    _up = region_overview.nlargest(5, "Δ ЕР, п.п.")
    _down = region_overview.nsmallest(5, "Δ ЕР, п.п.")
    _corr = region_overview["ЕР, % 2021"].corr(region_overview["Δ ЕР, п.п."])
    mo.md(
        f"""
    ## 3. Регионы

    Явка и результат «Единой России» по регионам на участках, 2026 против 2021. ДЭГ здесь не учтён,
    поэтому в регионах, где многие голосовали электронно (прежде всего Москва), явка на участках низкая.
    Регионы, где опубликованы протоколы меньше чем {MIN_UIKS} УИКов, не показаны.

    Результат ЕР вырос в {(region_overview["Δ ЕР, п.п."] > 0).sum()} регионах из {len(region_overview)}. Сильнее всего —
    там, где в 2021 году он был низким: {_names(_up)}. Снизился он в основном в национальных республиках
    с традиционно высокими цифрами: {_names(_down)}. Регионы «выравниваются»: корреляция между результатом 2021 года
    и его изменением — {_corr:.2f}.
    """
    )
    return


@app.cell
def region_overview(elections, pd):
    MIN_UIKS = 20  # регионы, где опубликованы протоколы лишь единичных УИКов, не сравниваем


    def _region_agg(d):
        g = d.groupby("region").agg(n=("uik", "size"), voters=("voters", "sum"), given=("given", "sum"),
                                    received=("received", "sum"), leader=("leader", "sum"))
        return pd.DataFrame({"УИКов": g["n"], "Избирателей": g["voters"],
                             "Явка, %": 100 * g["given"] / g["voters"], "ЕР, %": 100 * g["leader"] / g["received"]})


    region_overview = (
        _region_agg(elections[2026]).join(_region_agg(elections[2021]), lsuffix=" 2026", rsuffix=" 2021", how="inner")
        .assign(**{"Δ явки, п.п.": lambda t: t["Явка, % 2026"] - t["Явка, % 2021"],
                   "Δ ЕР, п.п.": lambda t: t["ЕР, % 2026"] - t["ЕР, % 2021"]})
        .round(1).rename_axis("Регион").reset_index()
        [["Регион", "УИКов 2026", "Явка, % 2021", "Явка, % 2026", "Δ явки, п.п.", "ЕР, % 2021", "ЕР, % 2026", "Δ ЕР, п.п."]]
        .query("`УИКов 2026` >= @MIN_UIKS")
        .sort_values("Δ ЕР, п.п.", ascending=False, ignore_index=True)
    )
    return MIN_UIKS, region_overview


@app.cell
def fig_region_shift(mo, plt, region_overview):
    def _fig_region_shift():
        t = region_overview
        fig, ax = plt.subplots(figsize=(11, 7), layout="constrained")
        ax.plot([0, 100], [0, 100], color="#999999", lw=1, ls="--")
        sc = ax.scatter(t["ЕР, % 2021"], t["ЕР, % 2026"], s=t["УИКов 2026"] / 8, c=t["Δ ЕР, п.п."],
                        cmap="RdBu_r", vmin=-30, vmax=30, edgecolor="k", linewidth=0.4, alpha=0.85)
        label = set(t.nlargest(3, "Δ ЕР, п.п.")["Регион"]) | set(t.nsmallest(3, "Δ ЕР, п.п.")["Регион"]) | {
            "город Москва", "город Санкт-Петербург", "Чеченская Республика", "Республика Татарстан (Татарстан)"}
        for _, r in t[t["Регион"].isin(label)].iterrows():
            ax.annotate(r["Регион"].replace("город ", "").replace("Республика ", "Респ. "),
                        (r["ЕР, % 2021"], r["ЕР, % 2026"]), textcoords="offset points", xytext=(6, 4), fontsize=8)
        fig.colorbar(sc, ax=ax, label="Изменение результата ЕР, п.п.", shrink=0.6)
        ax.set_xlim(15, 100)
        ax.set_ylim(15, 101)
        ax.set_xlabel("ЕР на участках в 2021, %")
        ax.set_ylabel("ЕР на участках в 2026, %")
        ax.set_title("Результат «Единой России» по регионам: 2021 → 2026 (размер точки — число УИКов)",
                     loc="left", fontweight="bold")
        return fig


    mo.vstack([_fig_region_shift(), mo.ui.table(region_overview, selection=None, page_size=10,
                                                label="Все регионы (сортировка по клику на заголовок)")])
    return


@app.cell(hide_code=True)
def region_explorer_controls(elections, mo):
    region_picker = mo.ui.dropdown(
        sorted(set(elections[2026]["region"]) & set(elections[2021]["region"])),
        value="город Санкт-Петербург", searchable=True, label="Регион",
    )
    mo.vstack([mo.md("### Посмотреть на регион поближе\\nКаждая точка — участок; серым — вся страна."), region_picker])
    return (region_picker,)


@app.cell
def fig_region_explorer(
    C_NEW,
    C_OLD,
    comet_axes,
    elections,
    jittered,
    plt,
    region_picker,
):
    def _fig_region(region):
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.6), layout="constrained")
        for ax, year in zip(axes, [2021, 2026]):
            d = jittered(elections[year])
            r = d[d["region"] == region]
            ax.scatter(d["x"], d["y"], s=0.3, c="#D5D5D5", linewidths=0, rasterized=True)
            ax.scatter(r["x"], r["y"], s=4, c=C_NEW if year == 2026 else C_OLD, linewidths=0)
            er = 100 * r["leader"].sum() / r["received"].sum()
            tu = 100 * r["given"].sum() / r["voters"].sum()
            comet_axes(ax, f"{year}: {len(r)} УИКов, явка {tu:.1f}%, ЕР {er:.1f}%")
        fig.suptitle(region, x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig


    _fig_region(region_picker.value)
    return


@app.cell(hide_code=True)
def anomalies_md(mo):
    mo.md(r"""
    ---
    # Часть II. Как распределены голоса по участкам

    Официальный итог — это сумма по почти 90 тысячам участков. Если посмотреть на сами участки,
    видно то, что сумма скрывает. На честных выборах участки образуют компактное облако: явка и
    результат меняются от места к месту, но без жёсткой связи. Два типичных следа фальсификаций:

    * **вбросы и «карусели»** — на участке одновременно растут явка и результат лидера, облако вытягивается
      в «хвост кометы» вправо-вверх;
    * **переписывание протоколов** — итоги подгоняют под «красивые» круглые проценты, и в распределении
      появляются пики на целых значениях.

    Статистическая аномалия — не доказательство фальсификации на конкретном участке, но массовые
    аномалии не возникают сами собой. Ниже — сводка по всем федеральным выборам с 2000 года (только бумажные УИКи).
    """)
    return


@app.cell
def summary(LEADER_NAME, PRESIDENTIAL, elections, pd):
    def _row(y, d):
        return {
            "Год": y,
            "Выборы": "президент" if y in PRESIDENTIAL else "Госдума",
            "Лидер": LEADER_NAME.get(y, "Единая Россия"),
            "УИКов": len(d),
            "Избирателей": int(d["voters"].sum()),
            "Явка, %": round(100 * d["given"].sum() / d["voters"].sum(), 2),
            "Результат лидера, %": round(100 * d["leader"].sum() / d["received"].sum(), 2),
        }


    summary_table = pd.DataFrame([_row(y, d) for y, d in elections.items()])
    summary_table
    return (summary_table,)


@app.cell(hide_code=True)
def fig1_md(mo):
    mo.md(r"""
    ## 4. Общая картина: «хвост» стал «телом»

    Каждая точка — один УИК: по горизонтали явка, по вертикали результат «Единой России».
    В 2021 году основная масса участков — плотное «ядро» около 35–40% явки и ~30% за ЕР, плюс «хвост кометы»
    вправо-вверх и сетка сгущений на круглых значениях. В 2026-м хвост превратился в многокластерное «тело»,
    а ядро истончилось.
    """)
    return


@app.cell
def fig_comets(comet_axes, elections, jittered, plt):
    def _fig_comets():
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.6), layout="constrained")
        for ax, year in zip(axes, [2021, 2026]):
            d = jittered(elections[year])
            ax.scatter(d["x"], d["y"], s=0.25, c="k", alpha=0.35, linewidths=0, rasterized=True)
            comet_axes(ax, f"{year}: {len(d):,} УИКов".replace(",", " "))
        fig.suptitle("Распределение УИКов по явке и результату «Единой России»",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig


    _fig_comets()
    return


@app.cell
def comet_core(DUMA_YEARS, elections, np, pd, summary_table):
    from scipy.ndimage import gaussian_filter


    def comet_core(df, sigma=2.0, window=(5, 90)):
        """Явка и результат лидера в точке максимальной плотности УИКов.

        Поиск ограничен окном `window`, чтобы не зацепить сгусток участков с явкой и результатом ~100%.
        """
        d = df[df["received"] > 0]
        edges = np.arange(0, 101, 1.0)
        h, _, _ = np.histogram2d(d["turnout"].clip(0, 99.99), d["result"].clip(0, 99.99), bins=[edges, edges])
        centers = edges[:-1] + 0.5
        m = (centers >= window[0]) & (centers <= window[1])
        s = gaussian_filter(h, sigma)[np.ix_(m, m)]
        i, j = np.unravel_index(np.argmax(s), s.shape)
        return centers[m][i], centers[m][j]


    def _core_row(y):
        x, r = comet_core(elections[y])
        ys = [comet_core(elections[y], s)[1] for s in (1, 2, 3, 4)]
        official = summary_table.set_index("Год").loc[y, "Результат лидера, %"]
        return {"Год": y, "Ядро: явка, %": x, "Ядро: ЕР, %": r,
                "Ядро: ЕР при σ=1…4": f"{min(ys)}–{max(ys)}",
                "Официально (бумага), %": official,
                "Официально − ядро, п.п.": round(official - r, 1)}


    core_table = pd.DataFrame([_core_row(y) for y in DUMA_YEARS])
    core_table
    return (core_table,)


@app.cell(hide_code=True)
def core_md(core_table, mo):
    _c = core_table.set_index("Год")
    mo.md(
        f"""
    ### Где находится «ядро» кометы

    Ядро — область, где сосредоточено больше всего участков (максимум сглаженной плотности УИКов на
    плоскости «явка × результат», сетка 1 п.п., сглаживание σ = 2 п.п.; сгусток у 100%/100% исключён).
    Если считать участки в ядре наименее затронутыми аномалиями, их результат — ориентир для «чистого» результата.

    В 2021 году ядро было на уровне **{_c.loc[2021, "Ядро: ЕР, %"]}%** за «Единую Россию», в 2026-м —
    **{_c.loc[2026, "Ядро: ЕР, %"]}%** (при σ от 1 до 4 п.п.: {_c.loc[2026, "Ядро: ЕР при σ=1…4"]}%). То есть
    в ядре поддержка партии выросла лишь на ~3 п.п., а официальный результат по участкам — на
    {_c.loc[2026, "Официально (бумага), %"] - _c.loc[2021, "Официально (бумага), %"]:.1f} п.п.
    Разрыв между официальным результатом и ядром вырос с {_c.loc[2021, "Официально − ядро, п.п."]} до
    **{_c.loc[2026, "Официально − ядро, п.п."]} п.п.** — это максимум за все думские выборы.
    """
    )
    return


@app.cell(hide_code=True)
def regions_md(mo):
    mo.md(r"""
    ## 5. Картина по регионам: «московский столб»

    Слева от основного кластера в 2026 году появился разреженный вертикальный «столб» — это бумажные участки Москвы.
    Сдвиг влево объясняется ДЭГ: большинство москвичей голосовали дистанционно, и на участки пришли немногие.
    Петербург в 2021-м был похож на Москву, а в 2026-м «уехал» в противоположную сторону. Чечня не изменилась.
    """)
    return


@app.cell
def fig_regions(comet_axes, elections, jittered, plt):
    REGION_GROUPS = {
        "Москва": (["город Москва"], "#D9725B"),
        "Санкт-Петербург": (["город Санкт-Петербург"], "#5B84D6"),
        "Крым и Севастополь": (["Республика Крым", "город Севастополь"], "#8E6BBF"),
        "Чеченская республика": (["Чеченская Республика"], "#5FB3A8"),
    }


    def _fig_regions():
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.9), layout="constrained")
        for ax, year in zip(axes, [2021, 2026]):
            d = jittered(elections[year])
            ax.scatter(d["x"], d["y"], s=0.4, c="#CFCFCF", linewidths=0, rasterized=True)
            for label, (names, color) in REGION_GROUPS.items():
                r = d[d["region"].isin(names)]
                ax.scatter(r["x"], r["y"], s=2, c=color, linewidths=0, label=label, rasterized=True)
            comet_axes(ax, str(year))
        axes[0].legend(loc="upper left", markerscale=5, frameon=False, fontsize=9)
        fig.suptitle("Распределение УИКов по разным регионам", x=0.01, ha="left",
                     fontsize=14, fontweight="bold")
        return fig


    _fig_regions()
    return (REGION_GROUPS,)


@app.cell
def region_tables(REGION_GROUPS, elections, mo, pd):
    def _region_stats(year, names):
        d = elections[year]
        d = d[d["region"].isin(names)]
        return {"УИКов": len(d),
                "Явка на участках, %": round(100 * d["given"].sum() / d["voters"].sum(), 1),
                "ЕР, %": round(100 * d["leader"].sum() / d["received"].sum(), 1),
                "Разброс ЕР по УИКам (IQR), п.п.": round(d["result"].quantile(0.75) - d["result"].quantile(0.25), 1)}


    region_table = pd.DataFrame([
        {"Регион": label, "Год": year, **_region_stats(year, names)}
        for label, (names, _) in REGION_GROUPS.items() for year in (2021, 2026)
    ])
    mo.ui.table(region_table, selection=None)
    return (region_table,)


@app.cell(hide_code=True)
def history_md(mo):
    mo.md(r"""
    ## 6. Динамика по годам: хуже на думских выборах при Путине ещё не было

    Плотность голосов на плоскости «явка × результат ЕР» на шести думских выборах.
    Близкое к нормальному распределение 2003 года сначала превращается в «комету» с ядром и хвостом,
    а затем — в многокластерное облако, где «гауссово» ядро трудно выделить.
    """)
    return


@app.cell(hide_code=True)
def history_controls(mo):
    heat_weight = mo.ui.dropdown(
        {"голосам (избирателям)": "voters", "участкам (УИКам)": "stations"},
        value="голосам (избирателям)", label="Взвешивать по",
    )
    heat_bin = mo.ui.dropdown({"0.5 п.п.": 0.5, "1 п.п.": 1.0}, value="0.5 п.п.", label="Шаг сетки")
    mo.hstack([heat_weight, heat_bin], justify="start")
    return heat_bin, heat_weight


@app.cell
def fig_history(
    DUMA_YEARS,
    elections,
    heat_bin,
    heat_weight,
    jittered,
    np,
    plt,
):
    from matplotlib.colors import PowerNorm


    def _fig_history(weight, step):
        fig, axes = plt.subplots(2, 3, figsize=(11, 7.6), layout="constrained")
        edges = np.arange(0, 100 + step, step)
        for ax, year in zip(axes.flat, DUMA_YEARS):
            d = jittered(elections[year])
            w = d["voters"] if weight == "voters" else None
            h, _, _ = np.histogram2d(d["x"], d["y"], bins=[edges, edges], weights=w)
            ax.imshow(h.T, origin="lower", extent=(0, 100, 0, 100), cmap="inferno",
                      norm=PowerNorm(0.5, vmin=0, vmax=np.percentile(h[h > 0], 99.7)),
                      interpolation="nearest")
            ax.text(6, 88, str(year), color="w", fontsize=12)
            ax.set_xticks([0, 50, 100])
            ax.set_yticks([0, 50, 100])
            ax.tick_params(labelsize=8)
        fig.supxlabel("Явка, %")
        fig.supylabel("Результат «Единой России», %")
        fig.suptitle("Распределение голосов по явке и результату партии власти на думских выборах",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig


    _fig_history(heat_weight.value, heat_bin.value)
    return


@app.cell(hide_code=True)
def peaks_md(mo):
    mo.md(r"""
    ## 7. Пики на «красивых» значениях: их стало намного больше

    Гистограмма УИКов по явке и по результату ЕР с шагом 0.1 п.п. (к числителю добавлен шум U(−0.5, 0.5),
    чтобы убрать артефакты деления на малых участках — как у Кобака и соавторов). При честном подсчёте
    заметных пиков на целых процентах быть не должно; при «рисовании» протоколов они появляются.
    """)
    return


@app.cell(hide_code=True)
def peaks_controls(ALL_YEARS, mo):
    compare_year = mo.ui.dropdown(
        {str(y): y for y in ALL_YEARS if y != 2026}, value="2021", label="Сравнить 2026 год с"
    )
    compare_year
    return (compare_year,)


@app.cell
def peaks_helper(C_NEW, C_OLD, elections, jittered, np, plt):
    def fig_peaks(old, new=2026, step=0.1):
        edges = np.arange(-step / 2, 100 + step / 2, step)
        centers = edges[:-1] + step / 2
        fig, axes = plt.subplots(2, 1, figsize=(11, 7.2), layout="constrained")
        for ax, col, label in zip(axes, ["x", "y"], ["Явка", "Результат лидера"]):
            for year, color in [(old, C_OLD), (new, C_NEW)]:
                h, _ = np.histogram(jittered(elections[year], for_histogram=True)[col], bins=edges)
                ax.plot(centers, h, lw=0.9, color=color, label=str(year))
            ax.set_xlim(0, 100)
            ax.set_xticks(range(0, 101, 5))
            ax.grid(axis="x", color="#CCCCCC", lw=0.8)
            ax.set_title(label, loc="left", fontweight="bold")
            ax.set_xlabel(f"{label}, %")
            ax.set_ylabel("Количество УИКов")
            ax.legend(frameon=False, ncols=2, loc="upper right")
        fig.suptitle(f"Пики на целочисленных значениях явки и результата — в {old} году и сейчас",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig

    return (fig_peaks,)


@app.cell
def fig_peaks_compare(compare_year, fig_peaks):
    fig_peaks(compare_year.value)
    return


@app.cell
def fig_peaks_2003(fig_peaks, mo):
    mo.vstack([
        mo.md("Сравнение с 2003 годом — так выглядит подсчёт без массовой подмены протоколов:"),
        fig_peaks(2003),
    ])
    return


@app.cell(hide_code=True)
def mc_md(mo):
    mo.md(r"""
    ## 8. Сколько УИКов с аномально круглыми значениями

    Методика [Кобака, Шпилькина и Пшеничникова](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/j.1740-9713.2018.01141.x):
    считаем УИКи, у которых явка **или** результат лидера лежит в пределах ±0.05 п.п. от целого процента,
    и вычитаем ожидаемое число таких УИКов при честном подсчёте. Ожидание получаем методом Монте-Карло:
    для каждого участка голоса за лидера и выданные бюллетени 1000 раз разыгрываются из биномиального
    распределения с теми же параметрами. «Порог случайных пиков» — 99.9-й перцентиль случайного превышения:
    всё, что выше, случайностью объяснить нельзя.
    """)
    return


@app.cell
def mc_func(np):
    def integer_anomaly(df, nrep=1000, prctl=99.9, seed=42, binwidth=0.1, chunk=50):
        """Тест Кобака–Шпилькина–Пшеничникова на избыток «целых» процентов.

        Наблюдаемое число УИКов, у которых явка или результат лидера попадает в ±binwidth/2 от целого
        процента, сравнивается с Монте-Карло: для каждого УИКа голоса за лидера и выданные бюллетени
        заново разыгрываются из биномиального распределения с теми же n и p (1000 повторов).
        Критерии включения — как в AOAS-2016: ≥100 избирателей, явка и результат ≤ 99%.
        """
        d = df[(df["received"] > 0) & (df["voters"] >= 100)]
        d = d[(d["given"] / d["voters"] <= 0.99) & (d["leader"] / d["received"] <= 0.99)]
        V, G = d["voters"].to_numpy(), d["given"].to_numpy()
        R, L = d["received"].to_numpy(), d["leader"].to_numpy()

        def near_int(p):
            return np.abs(p - np.round(p)) <= binwidth / 2

        def counts(lead, giv):  # → [явка или результат, только результат, только явка]
            res, tur = near_int(100 * lead / R), near_int(100 * giv / V)
            return np.stack([(res | tur).sum(-1), res.sum(-1), tur.sum(-1)], axis=-1)

        observed = counts(L, G)
        rng = np.random.default_rng(seed)
        sims = np.concatenate([
            counts(rng.binomial(R, L / R, size=(chunk, len(d))), rng.binomial(V, G / V, size=(chunk, len(d))))
            for _ in range(nrep // chunk)
        ])
        expected = sims.mean(0)
        return {
            "n": len(d),
            "observed": observed,
            "expected": expected,
            "excess": observed - expected,
            "std": sims.std(0),
            "threshold": np.percentile(sims, prctl, axis=0) - expected,
        }


    return (integer_anomaly,)


@app.cell
def mc_run(
    ALL_YEARS,
    DATA_DIR,
    PRESIDENTIAL,
    elections,
    integer_anomaly,
    json,
    mo,
    pd,
):
    def _cached_anomaly(key, df, cache_path=DATA_DIR / "integer_mc_cache.json"):
        """Монте-Карло детерминирован (seed=42), поэтому результат кэшируется по отпечатку данных."""
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        fp = f"{key}|{len(df)}|{df['voters'].sum()}|{df['given'].sum()}|{df['received'].sum()}|{df['leader'].sum()}"
        if fp not in cache:
            a = integer_anomaly(df)
            cache[fp] = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in a.items()}
            cache_path.write_text(json.dumps(cache))
        return cache[fp]


    _rows = []
    for _y in mo.status.progress_bar(ALL_YEARS, title="Монте-Карло по выборам"):
        _a = _cached_anomaly(str(_y), elections[_y])
        _rows.append({
            "Год": _y, "Выборы": "президент" if _y in PRESIDENTIAL else "Госдума", "УИКов в тесте": _a["n"],
            "Избыток: явка или результат": round(_a["excess"][0], 1),
            "Избыток: только явка": round(_a["excess"][2], 1),
            "Избыток: только результат": round(_a["excess"][1], 1),
            "Порог случайных пиков": round(_a["threshold"][0], 1),
            "σ случайного разброса": round(_a["std"][0], 1),
        })
    integer_table = pd.DataFrame(_rows)
    integer_table
    return (integer_table,)


@app.cell
def fig_integer(PRESIDENTIAL, integer_table, np, plt):
    def _fig_integer():
        t = integer_table
        x = np.arange(len(t))
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        ax.plot(x, t["Избыток: явка или результат"], "-o", color="k", lw=2, mfc="w", mew=1.5,
                label="Явка или результат лидера")
        ax.plot(x, t["Избыток: только явка"], "-o", color="#5B84D6", lw=1.2, ms=4, label="Только явка")
        ax.plot(x, t["Избыток: только результат"], "-o", color="#D9725B", lw=1.2, ms=4, label="Только результат")
        ax.plot(x, t["Порог случайных пиков"], "--", color="#999999", lw=1.2, label="Порог случайных пиков (99.9%)")
        for xi, v in zip(x, t["Избыток: явка или результат"]):
            ax.annotate(f"{v:.0f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
        ax.set_xticks(x, [f"{y}\n{'П' if y in PRESIDENTIAL else 'Д'}" for y in t["Год"]])
        ax.set_ylabel("Избыток УИКов с «красивыми» значениями")
        ax.legend(frameon=False, loc="upper left")
        ax.set_title("Количество УИКов с «красивыми» значениями на парламентских (Д) и президентских (П) выборах",
                     loc="left", fontweight="bold")
        return fig


    _fig_integer()
    return


@app.cell(hide_code=True)
def conclusions(
    core_table,
    deg_table,
    integer_table,
    mo,
    parties,
    region_table,
    turnout,
):
    _c = core_table.set_index("Год")
    _i = integer_table.set_index("Год")
    _p = {y: parties[y].set_index("Партия")["%"] for y in (2021, 2026)}
    _duma = _i[_i["Выборы"] == "Госдума"]["Избыток: явка или результат"]
    _r = region_table.set_index(["Регион", "Год"])
    mo.md(
        f"""
    ---
    ## Выводы

    1. **«Единая Россия» получила {_p[2026]["Единая Россия"]:.1f}%** против {_p[2021]["Единая Россия"]:.1f}% в 2021 году,
       КПРФ — {_p[2026]["КПРФ"]:.1f}% (было {_p[2021]["КПРФ"]:.1f}%). Явка с учётом ДЭГ — {turnout[2026]["явка"]:.1f}%.
    2. **Электронное голосование стало массовым**: через ДЭГ проголосовали {turnout[2026]["доля ДЭГ"]:.1f}% пришедших,
       в Москве — {deg_table.set_index("Регион").loc["город Москва", "Доля ДЭГ, %"]}%. Бумажные участки Москвы превратились
       в вертикальный «столб» с явкой около {_r.loc[("Москва", 2026), "Явка на участках, %"]}% и огромным разбросом результата.
    3. **«Хвост кометы» стал «телом»**: ядро участков сдвинулось лишь до {_c.loc[2026, "Ядро: ЕР, %"]}% за ЕР, а разрыв между
       официальным результатом и ядром вырос до {_c.loc[2026, "Официально − ядро, п.п."]} п.п. — больше, чем на любых
       предыдущих думских выборах.
    4. **Круглых процентов стало вдвое больше**: избыток УИКов с «красивыми» значениями — {_i.loc[2026, "Избыток: явка или результат"]:.0f}
       против {_i.loc[2021, "Избыток: явка или результат"]:.0f} в 2021 году. Это рекорд для думских выборов (прежний —
       {_duma.drop(2026).max():.0f} в {_duma.drop(2026).idxmax()} году); больше было только на президентских выборах 2024 года
       ({_i.loc[2024, "Избыток: явка или результат"]:.0f}).
    5. **Петербург** резко сменил профиль: явка на участках {_r.loc[("Санкт-Петербург", 2021), "Явка на участках, %"]}% → {_r.loc[("Санкт-Петербург", 2026), "Явка на участках, %"]}%,
       ЕР {_r.loc[("Санкт-Петербург", 2021), "ЕР, %"]}% → {_r.loc[("Санкт-Петербург", 2026), "ЕР, %"]}%. **Чечня** — почти без изменений
       (ЕР {_r.loc[("Чеченская республика", 2021), "ЕР, %"]}% → {_r.loc[("Чеченская республика", 2026), "ЕР, %"]}%).

    По совокупности признаков это самые аномальные думские выборы за всё время наблюдений.
    """
    )
    return


@app.cell(hide_code=True)
def game_intro(mo):
    mo.md(r"""
    ---
    # Часть III. Игра: сфальсифицируй выборы и останься незаметным

    Вы — председатель территориальной избирательной комиссии небольшого города. Администрация
    спустила задание: обеспечить нужную явку и результат «Единой России» — и выделила на это бюджет.
    В вашем распоряжении 12 участков. Избиратели голосуют как голосуют, а исправлять итоги придётся вам.

    | Метод | Что происходит | Цена |
    |---|---|---|
    | 🏢 **Мобилизация** | бюджетников и работников предприятий приводят на участок под контролем; голосуют почти все «как надо» | 0.5 тыс. ₽ за человека, до 8% списка |
    | 🎠 **Карусель** | одни и те же люди голосуют на участке несколько раз | 1 тыс. ₽ за голос, до 150 на участок |
    | 🗳 **Вброс** | пачка бюллетеней за ЕР в урну — например, ночью, пока бюллетени лежат в комиссии | сговор с комиссией 150 тыс. ₽ + 0.1 тыс. за бюллетень |
    | 🔀 **Перекладка** | при подсчёте часть бюллетеней других партий кладут в стопку ЕР | сговор с комиссией 150 тыс. ₽ (один на вброс и перекладку) |
    | ✍️ **Переписать протокол** | в ТИК протокол рисуют с нуля: любые проценты явки и ЕР | 300 тыс. ₽ за участок |
    | 🚓 **Убрать наблюдателя** | на трёх участках есть независимые наблюдатели 👁 | 200 тыс. ₽ |

    Мобилизация, карусель, вброс и перекладка складываются; переписанный протокол заменяет всё остальное.
    Подделка на участке с наблюдателем без его удаления закончится актом о нарушении.

    Когда закончите — сдайте протоколы. Их проверит аналитик теми же методами, что в Части II:
    сравнит ваш город с соседними, поищет круглые проценты, выбросы и участки, нарисованные «под линейку».
    Игра навеяна [экспериментом с монеткой Винсента Вармердама](https://www.youtube.com/watch?v=IrlNG-jmzx8):
    люди, которые пытаются выдумать «случайные» броски, почти всегда выдают себя.
    """)
    return


@app.cell
def game_model(core_table, elections, np):
    GAME_UIKS = 12
    GAME_LEVELS = {  # цель по ЕР, цель по явке, бюджет в тыс. ₽
        "Скромное: ЕР ≥ 40%, явка ≥ 42%, бюджет 1.5 млн ₽": (40, 42, 1500),
        "Обычное: ЕР ≥ 50%, явка ≥ 50%, бюджет 3 млн ₽": (50, 50, 3000),
        "Как надо: ЕР ≥ 65%, явка ≥ 65%, бюджет 4.5 млн ₽": (65, 65, 4500),
        "Образцовое: ЕР ≥ 90%, явка ≥ 90%, бюджет 6 млн ₽": (90, 90, 6000),
    }
    GAME_OBSERVERS = 3  # участков с независимыми наблюдателями
    GAME_PRICES = {  # тыс. ₽
        "mobilize": 0.5,     # за приведённого избирателя
        "carousel": 1.0,     # за голос «карусели»
        "commission": 150,   # сговор с руководством УИК: нужен для вброса и перекладки
        "stuff": 0.1,        # за вброшенный бюллетень
        "rewrite": 300,      # переписать протокол в ТИК
        "observer": 200,     # убрать наблюдателя
    }
    MOBILIZED_ER_SHARE = 0.85  # приведённые под контролем голосуют в основном «как надо»


    def fraud_cost(c, voters):
        """Стоимость выбранных методов на одном участке, тыс. ₽."""
        if c["rewrite"]:
            cost = GAME_PRICES["rewrite"]
        else:
            cost = (round(voters * c["mobilize"] / 100) * GAME_PRICES["mobilize"]
                    + c["carousel"] * GAME_PRICES["carousel"]
                    + (GAME_PRICES["commission"] if c["stuff"] or c["shift"] else 0)
                    + c["stuff"] * GAME_PRICES["stuff"])
        return cost + (GAME_PRICES["observer"] if c["remove_observer"] else 0)
    TOWN_NAMES = ["Верхнеключевск", "Нижнеозёрск", "Красноборск", "Светлогорье", "Приреченск",
                  "Каменск-Северный", "Заречный", "Новодольск", "Сосновоборск", "Белоярск"]
    # размеры участков берём из реальных УИКов 2026 года; уровень явки и поддержки ЕР — из «ядра» 2026 года
    GAME_SIZES = elections[2026].query("800 <= voters <= 3000")["voters"].to_numpy()
    GAME_CORE_TURNOUT, GAME_CORE_RESULT = (core_table.set_index("Год").loc[2026, ["Ядро: явка, %", "Ядро: ЕР, %"]] / 100)


    def simulate_towns(rng, sizes):
        """Честные выборы в городах: sizes — массив (города × участки) с числом избирателей.

        У каждого города свой средний уровень явки и поддержки ЕР, у каждого участка — свой разброс вокруг
        него, а голоса — биномиальный шум вокруг этих вероятностей.
        """
        towns = sizes.shape[0]
        t_mu = rng.normal(GAME_CORE_TURNOUT, 0.03, (towns, 1))
        r_mu = rng.normal(GAME_CORE_RESULT, 0.03, (towns, 1))
        pt = np.clip(t_mu + rng.normal(0, 0.045, sizes.shape), 0.1, 0.9)
        pr = np.clip(r_mu + rng.normal(0, 0.05, sizes.shape), 0.05, 0.9)
        given = rng.binomial(sizes, pt)
        received = given - rng.binomial(given, 0.002)  # пара бюллетеней всегда уносят домой
        invalid = rng.binomial(received, 0.012)
        leader = rng.binomial(received - invalid, pr)
        return {"voters": sizes, "given": given, "received": received, "invalid": invalid, "leader": leader}


    def with_percentages(df):
        return df.assign(turnout=100 * df["given"] / df["voters"], result=100 * df["leader"] / df["received"])

    return (
        GAME_LEVELS,
        GAME_OBSERVERS,
        GAME_SIZES,
        GAME_UIKS,
        MOBILIZED_ER_SHARE,
        TOWN_NAMES,
        fraud_cost,
        simulate_towns,
        with_percentages,
    )


@app.cell(hide_code=True)
def game_setup(GAME_LEVELS, mo):
    game_level = mo.ui.dropdown(list(GAME_LEVELS), value="Обычное: ЕР ≥ 50%, явка ≥ 50%, бюджет 3 млн ₽", label="Задание")
    game_new = mo.ui.button(value=0, on_click=lambda v: v + 1, label="🎲 Другой город")
    mo.hstack([game_level, game_new], justify="start", gap=2)
    return game_level, game_new


@app.cell(hide_code=True)
def game_world(
    GAME_LEVELS,
    GAME_OBSERVERS,
    GAME_SIZES,
    GAME_UIKS,
    TOWN_NAMES,
    game_level,
    game_new,
    mo,
    np,
    pd,
    simulate_towns,
    with_percentages,
):
    game_seed = 2026 + game_new.value
    _rng = np.random.default_rng(game_seed)
    _sim = simulate_towns(_rng, _rng.choice(GAME_SIZES, (31, GAME_UIKS)))
    game_name = TOWN_NAMES[game_new.value % len(TOWN_NAMES)]
    game_town = with_percentages(pd.DataFrame({k: v[0] for k, v in _sim.items()}))  # ваш город, честные итоги
    game_town.insert(0, "УИК", [f"№{n}" for n in np.sort(_rng.choice(np.arange(1101, 1400), GAME_UIKS, replace=False))])
    game_region = with_percentages(pd.DataFrame({k: v[1:].ravel() for k, v in _sim.items()})).assign(
        town=np.repeat(np.arange(30), GAME_UIKS))  # 30 соседних городов, голосуют честно
    game_observers = {int(i) for i in _rng.choice(GAME_UIKS, GAME_OBSERVERS, replace=False)}
    game_target_result, game_target_turnout, game_budget = GAME_LEVELS[game_level.value]

    mo.md(
        f"""
    ### 🏙 {game_name}

    {GAME_UIKS} участков, {game_town["voters"].sum():,} избирателей. По честному подсчёту ожидается явка
    **{100 * game_town["given"].sum() / game_town["voters"].sum():.1f}%** и **{100 * game_town["leader"].sum() / game_town["received"].sum():.1f}%**
    за «Единую Россию». Администрация ждёт явку не ниже **{game_target_turnout}%** и результат не ниже **{game_target_result}%**
    и выделяет **{game_budget / 1000:.1f} млн ₽**. На участках {", ".join(game_town["УИК"].iloc[sorted(game_observers)])} работают наблюдатели 👁.
    """.replace(",", " ")
    )
    return (
        game_budget,
        game_name,
        game_observers,
        game_region,
        game_target_result,
        game_target_turnout,
        game_town,
    )


@app.cell(hide_code=True)
def game_controls(game_observers, game_town, mo):
    def _uik_controls(r, observed):
        return mo.ui.dictionary({
            "mobilize": mo.ui.slider(0, 8, step=1, value=0, show_value=True, full_width=True),
            "carousel": mo.ui.slider(0, 150, step=10, value=0, show_value=True, full_width=True),
            "stuff": mo.ui.slider(0, 1000, step=10, value=0, show_value=True, full_width=True),
            "shift": mo.ui.slider(0, 100, step=5, value=0, show_value=True, full_width=True),
            "rewrite": mo.ui.switch(),
            "t": mo.ui.number(start=0, stop=100, step=0.01, value=round(r.turnout, 2), full_width=True),
            "r": mo.ui.number(start=0, stop=100, step=0.01, value=round(r.result, 2), full_width=True),
            "remove_observer": mo.ui.switch(label="🚓 убрать", disabled=not observed),
        })


    game_controls = mo.ui.array([_uik_controls(r, i in game_observers) for i, r in enumerate(game_town.itertuples())])


    def _cell(title, widget):
        return mo.vstack([mo.md(f"<span style='font-size:.8em;opacity:.7'>{title}</span>"), widget], gap=0)


    def _uik_card(i, r):
        c = game_controls[i]
        observer = i in game_observers
        head = mo.md(f"**УИК {r.УИК}** {'👁' if observer else ''}<br>"
                     f"<span style='opacity:.65;font-size:.85em'>{r.voters} изб. · честно {r.turnout:.1f}% / {r.result:.1f}%</span>")
        polling = mo.hstack([_cell("🏢 мобилизация, % списка", c["mobilize"]), _cell("🎠 карусель, голосов", c["carousel"]),
                             _cell("🗳 вброс, бюллетеней", c["stuff"]), _cell("🔀 перекладка, % чужих", c["shift"])],
                            widths="equal", gap=1)
        tik = mo.hstack([_cell("✍️ переписать", c["rewrite"]), _cell("явка в протоколе, %", c["t"]),
                         _cell("ЕР в протоколе, %", c["r"]), _cell("наблюдатель", c["remove_observer"] if observer else mo.md("—"))],
                        widths=[0.8, 1, 1, 1], gap=1)
        return mo.hstack([head, mo.vstack([polling, tik], gap=0.3)], widths=[1, 5], align="center", gap=1)


    mo.vstack([_uik_card(i, r) for i, r in enumerate(game_town.itertuples())], gap=1.2)
    return (game_controls,)


@app.cell(hide_code=True)
def game_apply(
    GAME_UIKS,
    MOBILIZED_ER_SHARE,
    fraud_cost,
    game_budget,
    game_controls,
    game_observers,
    game_target_result,
    game_target_turnout,
    game_town,
    mo,
    np,
    pd,
    with_percentages,
):
    def apply_fraud(town, controls, seed=0):
        """Применить выбранные методы к честным итогам участков."""
        rng = np.random.default_rng(seed)
        out = town.copy()
        for i, c in enumerate(controls):
            voters, given, received, invalid, leader = (int(out.at[i, k]) for k in
                                                        ["voters", "given", "received", "invalid", "leader"])
            if c["rewrite"]:
                new_given = round(voters * c["t"] / 100)
                new_received = round(new_given * received / given)
                invalid = round(new_received * invalid / received)
                leader = min(round(new_received * c["r"] / 100), new_received - invalid)
                given, received = new_given, new_received
            else:
                mobilized = round(voters * c["mobilize"] / 100)
                added = mobilized + c["carousel"] + c["stuff"]
                leader += rng.binomial(mobilized, MOBILIZED_ER_SHARE) + c["carousel"] + c["stuff"]
                given, received = given + added, received + added
                leader += round((received - invalid - leader) * c["shift"] / 100)
            out.loc[i, ["given", "received", "invalid", "leader"]] = [given, received, invalid, leader]
        return with_percentages(out)


    game_result = apply_fraud(game_town, game_controls.value)
    game_costs = [fraud_cost(c, v) for c, v in zip(game_controls.value, game_town["voters"])]
    game_spent = sum(game_costs)
    game_turnout = 100 * game_result["given"].sum() / game_result["voters"].sum()
    game_er = 100 * game_result["leader"].sum() / game_result["received"].sum()
    game_mission_ok = game_turnout >= game_target_turnout and game_er >= game_target_result and game_spent <= game_budget


    def _progress(label, value, target, honest):
        return mo.stat(f"{value:.1f}%", label=label, bordered=True,
                       caption=f"цель ≥ {target}% · честно {honest:.1f}%",
                       direction="increase" if value >= target else "decrease")


    _per_uik = pd.DataFrame({
        "УИК": game_town["УИК"] + [" 👁" if i in game_observers else "" for i in range(GAME_UIKS)],
        "Явка: честно → сдано": [f"{a:.1f}% → {b:.1f}%" for a, b in zip(game_town["turnout"], game_result["turnout"])],
        "ЕР: честно → сдано": [f"{a:.1f}% → {b:.1f}%" for a, b in zip(game_town["result"], game_result["result"])],
        "Голосов ЕР добавлено": game_result["leader"] - game_town["leader"],
        "Потрачено, тыс. ₽": np.round(game_costs, 1),
    })

    mo.vstack([
        mo.hstack([
            _progress("Явка по городу", game_turnout, game_target_turnout,
                      100 * game_town["given"].sum() / game_town["voters"].sum()),
            _progress("«Единая Россия»", game_er, game_target_result,
                      100 * game_town["leader"].sum() / game_town["received"].sum()),
            mo.stat(f"{game_spent / 1000:.2f} млн ₽", label="Потрачено", bordered=True,
                    caption=f"из {game_budget / 1000:.1f} млн · осталось {(game_budget - game_spent) / 1000:.2f}",
                    direction="increase" if game_spent <= game_budget else "decrease"),
            mo.stat("✅ выполнено" if game_mission_ok else "🚫 перерасход" if game_spent > game_budget else "⏳ пока нет",
                    label="Задание", bordered=True),
        ], justify="start", wrap=True),
        mo.accordion({"Итоги и расходы по участкам": mo.ui.table(_per_uik, selection=None, page_size=GAME_UIKS)}),
    ])
    return game_er, game_mission_ok, game_result, game_spent, game_turnout


@app.cell(hide_code=True)
def game_submit(mo):
    game_submit = mo.ui.run_button(label="📨 Сдать протоколы", kind="warn")
    mo.hstack([game_submit, mo.md("<span style='opacity:.65'>После любых правок протоколы нужно сдать заново.</span>")],
              justify="start", align="center")
    return (game_submit,)


@app.cell
def game_detector(np, pd, simulate_towns):
    def _spearman(x, y):
        """Корреляция Спирмена по последней оси (работает и для пачки симуляций)."""
        rx, ry = x.argsort(-1).argsort(-1), y.argsort(-1).argsort(-1)
        rx, ry = rx - rx.mean(-1, keepdims=True), ry - ry.mean(-1, keepdims=True)
        return (rx * ry).sum(-1) / np.sqrt((rx ** 2).sum(-1) * (ry ** 2).sum(-1))


    def _mahalanobis(x, pts):
        d = x - pts.mean(0)
        return np.sqrt(np.einsum("...i,ij,...j->...", d, np.linalg.inv(np.cov(pts.T)), d))


    def investigate(res, region, nsim=2000, seed=0):
        """Проверки аналитика. Возвращает таблицу проверок и индекс подозрительности 0–100."""
        rng = np.random.default_rng(seed)
        V, G, R, L = (res[k].to_numpy() for k in ["voters", "given", "received", "leader"])
        t, r = 100 * G / V, 100 * L / R
        rows = []

        def add(name, found, norm, points):
            rows.append({"Проверка": name, "Что видит аналитик": found, "Норма для честного подсчёта": norm, "Штраф": points})

        over = int((G > V).sum())
        add("Невозможные значения", f"участков с явкой больше 100%: {over}", "0", 100 if over else 0)

        near = lambda p: np.abs(p - np.round(p)) <= 0.05
        obs_round = int((near(t) | near(r)).sum())
        sim_round = (near(100 * rng.binomial(V, np.minimum(G / V, 1), (nsim, len(V))) / V)
                     | near(100 * rng.binomial(R, L / R, (nsim, len(V))) / R)).sum(1)
        p_round = (sim_round >= obs_round).mean()
        add("Круглые проценты", f"{obs_round} из {len(V)} участков с целым процентом явки или ЕР",
            f"в среднем {sim_round.mean():.1f}; шанс случайно получить столько: {p_round:.1%}",
            40 if p_round < 0.001 else 30 if p_round < 0.01 else 15 if p_round < 0.05 else 0)

        towns = region.groupby("town")[["voters", "given", "received", "leader"]].sum()
        town_pts = np.column_stack([100 * towns["given"] / towns["voters"], 100 * towns["leader"] / towns["received"]])
        d_town = float(_mahalanobis(np.array([100 * G.sum() / V.sum(), 100 * L.sum() / R.sum()]), town_pts))
        add("Город на фоне соседей", f"отклонение от соседних городов: {d_town:.1f}σ", "до 2.5σ",
            40 if d_town > 4 else 25 if d_town > 3 else 10 if d_town > 2.5 else 0)

        reg_pts = region[["turnout", "result"]].to_numpy()
        n_out = int((_mahalanobis(np.column_stack([t, r]), reg_pts) > 3).sum())
        expected_out = (_mahalanobis(reg_pts, reg_pts) > 3).mean() * len(V)
        add("Участки-выбросы", f"{n_out} участков дальше 3σ от облака соседних участков",
            f"в среднем {expected_out:.1f}", min(30, 10 * max(0, n_out - 1)))

        honest = simulate_towns(rng, np.tile(V, (nsim, 1)))
        st, sr = 100 * honest["given"] / V, 100 * honest["leader"] / honest["received"]
        rho, rho_sim = _spearman(t, r), _spearman(st, sr)
        p_rho = (rho_sim >= rho).mean()
        add("Связь явки и результата", f"корреляция по участкам города: {rho:+.2f}",
            f"обычно от {np.percentile(rho_sim, 5):+.2f} до {np.percentile(rho_sim, 95):+.2f}",
            20 if p_rho < 0.01 else 10 if p_rho < 0.05 else 0)

        spread = min((st.std(1) <= t.std()).mean(), (sr.std(1) <= r.std()).mean())
        add("Слишком ровные участки", f"разброс между участками: явка ±{t.std():.1f}, ЕР ±{r.std():.1f} п.п.",
            f"обычно явка ±{np.median(st.std(1)):.1f}, ЕР ±{np.median(sr.std(1)):.1f} п.п.",
            20 if spread < 0.005 else 10 if spread < 0.025 else 0)

        table = pd.DataFrame(rows)
        return table, int(min(100, table["Штраф"].sum()))

    return (investigate,)


@app.cell(hide_code=True)
def game_verdict(
    game_budget,
    game_controls,
    game_er,
    game_mission_ok,
    game_observers,
    game_region,
    game_result,
    game_spent,
    game_submit,
    game_town,
    game_turnout,
    investigate,
    mo,
    pd,
):
    mo.stop(not game_submit.value, mo.md("_Настройте участки и нажмите «Сдать протоколы»._"))

    def _observer_reports(controls):
        """Что зафиксировали наблюдатели на своих участках."""
        rows = []
        for i in sorted(game_observers):
            c, uik = controls[i], game_town.at[i, "УИК"]
            commission_fraud = c["rewrite"] or c["stuff"] or c["shift"]
            if c["remove_observer"]:
                rows.append((f"наблюдателя на УИК {uik} удалили — жалоба разошлась по соцсетям", 5))
            elif commission_fraud:
                rows.append((f"на УИК {uik} наблюдатель составил акт и снял подделку на видео", 25))
            elif c["carousel"]:
                rows.append((f"на УИК {uik} наблюдатель заметил «карусель»", 10))
        return pd.DataFrame([{"Проверка": "Наблюдатели", "Что видит аналитик": text,
                              "Норма для честного подсчёта": "нарушений нет", "Штраф": points} for text, points in rows])


    _stats, _ = investigate(game_result, game_region)
    game_checks = pd.concat([_stats, _observer_reports(game_controls.value)], ignore_index=True)
    game_score = int(min(100, game_checks["Штраф"].sum()))
    game_honest_checks, game_honest_score = investigate(game_town, game_region, seed=1)
    game_caught = game_score >= 30

    _verdict = ("🕶 Незаметно" if game_score < 30 else "🔍 Подозрительно" if game_score < 60 else "🚨 Попались")
    _story = {
        (True, False): "Задание выполнено, а статистика ничего не заметила. Редкая удача — попробуйте повторить на другом городе.",
        (True, True): "Администрация довольна, но ваш город светится на графиках аналитиков. Такие цифры видно без всякого суда.",
        (False, False): ("Вы остались незаметны, но задание провалено: " +
                         ("бюджет превышен." if game_spent > game_budget else "до цели не дотянули.")),
        (False, True): "Худший исход: задание не выполнено, а следы подделки видны всем.",
    }[(game_mission_ok, game_caught)]

    mo.vstack([
        mo.callout(mo.md(f"""## {_verdict} — индекс подозрительности {game_score}/100

    **Задание:** {"✅ выполнено" if game_mission_ok else "❌ не выполнено"} (явка {game_turnout:.1f}%, ЕР {game_er:.1f}%,
    потрачено {game_spent / 1000:.2f} из {game_budget / 1000:.1f} млн ₽).
    {_story}"""), kind="success" if not game_caught else "warn" if game_score < 60 else "danger"),
        mo.ui.table(game_checks, selection=None, label="Разбор аналитика"),
        mo.md(f"""**Сравнение со случайностью.** Те же проверки для честного подсчёта в вашем городе дают индекс
    **{game_honest_score}/100**. Иногда и честные цифры выглядят странно — поэтому статистика указывает, где искать,
    но не выносит приговор отдельному участку."""),
    ])
    return


@app.cell(hide_code=True)
def game_figures(
    C_OLD,
    comet_axes,
    elections,
    game_name,
    game_region,
    game_result,
    game_submit,
    game_target_result,
    game_target_turnout,
    game_town,
    jittered,
    mo,
    plt,
):
    mo.stop(not game_submit.value)


    def _fig_game():
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5.6), layout="constrained")
        a1.scatter(game_region["turnout"], game_region["result"], s=8, c="#CFCFCF", linewidths=0, label="соседние города")
        a1.scatter(game_town["turnout"], game_town["result"], s=40, facecolors="none", edgecolors=C_OLD,
                   label="ваши участки, честно")
        for (_, h), (_, f) in zip(game_town.iterrows(), game_result.iterrows()):
            if (h["turnout"], h["result"]) != (f["turnout"], f["result"]):
                a1.annotate("", (f["turnout"], f["result"]), (h["turnout"], h["result"]),
                            arrowprops={"arrowstyle": "->", "color": "#999999", "lw": 0.8})
        a1.scatter(game_result["turnout"], game_result["result"], s=45, c="#D9725B", edgecolors="k",
                   linewidths=0.5, label="ваши участки, сданные", zorder=3)
        a1.axvline(game_target_turnout, color="#999999", ls=":", lw=1)
        a1.axhline(game_target_result, color="#999999", ls=":", lw=1)
        comet_axes(a1, f"{game_name} среди соседей")
        a1.legend(frameon=False, loc="upper left", fontsize=8)

        d = jittered(elections[2026])
        a2.scatter(d["x"], d["y"], s=0.25, c="#BBBBBB", linewidths=0, rasterized=True)
        a2.scatter(game_result["turnout"], game_result["result"], s=45, c="#D9725B", edgecolors="k",
                   linewidths=0.5, zorder=3)
        comet_axes(a2, "Ваши участки среди всех УИКов России-2026")
        return fig


    _fig_game()
    return


@app.cell(hide_code=True)
def game_epilogue(mo):
    mo.md(r"""
    ### Почему спрятаться почти невозможно

    * **Мобилизация и карусель** — живые (или почти живые) голоса, но они всё равно поднимают явку и результат
      одновременно. Немного — незаметно; много — город отрывается от соседей.
    * **Вброс** тянет явку и результат вверх вместе — участки вытягиваются в «хвост кометы».
    * **Перекладка** прячется лучше всего (явка не меняется), но требует сговора со всей комиссией на каждом участке —
      это дорого, и результат всё равно уезжает от соседних городов.
    * **Переписанный протокол** выдают сами числа. Придумывая «правдоподобные» проценты, люди тянутся к круглым
      значениям и рисуют участки «под линейку» — слишком похожими друг на друга. Как в эксперименте с монеткой,
      где выдуманные серии «орёл/решка» слишком ровные и без длинных повторов.
    * **Наблюдатели** видят подделку своими глазами, а убрать их — отдельный скандал.

    Скромное задание при небольшом бюджете иногда удаётся выполнить незаметно. «Образцовое» — никогда: именно такие
    цифры в реальных данных образуют пики на круглых значениях и хвосты комет из Части II.
    """)
    return


if __name__ == "__main__":
    app.run()
