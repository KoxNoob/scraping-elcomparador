# app.py
# Single-file Streamlit — ElComparador scraper (structure identique à ton ancienne app)
# FR : interface + scraping + Google Sheets dans un seul fichier.

import streamlit as st
import pandas as pd
import numpy as np
import time
import re
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

# -----------------------
# Configuration
# -----------------------
st.set_page_config(page_title="ElComparador - Odds Scraper", layout="wide")
st.title("⚽ ElComparador — Odds Scraper (single-file)")

# Ordre attendu sur ElComparador (utilisé pour associer les cotes par bookmaker)
BOOKMAKERS_ORDER = ["bet365", "codere", "williamhill", "bwin", "sportium", "888sport", "marathon", "betsson"]
BOOKMAKERS_DISPLAY = [bm.capitalize() for bm in BOOKMAKERS_ORDER]

# Google Sheet (ton lien)
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Uh4GWhTX6Q4g9jX6rOBNeqlRxW92VvrHYFm91DJ-3Iw/edit?gid=2029065601"

# -----------------------
# Helpers Google Sheets
# -----------------------
@st.cache_data(ttl=300)
def load_competitions_from_sheet(sheet_url: str) -> pd.DataFrame:
    """
    Retourne un DataFrame contenant au moins les colonnes 'Compétition' et 'URL'.
    Utilise st.secrets["GOOGLE_SHEET_CREDENTIALS"] (doit être un dict).
    """
    credentials_dict = st.secrets.get("GOOGLE_SHEET_CREDENTIALS")
    if not credentials_dict:
        st.error("Missing GOOGLE_SHEET_CREDENTIALS in Streamlit secrets. Ajoute le JSON du service account dans Settings -> Secrets.")
        return pd.DataFrame()

    try:
        creds = Credentials.from_service_account_info(
            credentials_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        client = gspread.authorize(creds)

        m = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
        if not m:
            st.error("URL Google Sheet invalide.")
            return pd.DataFrame()
        spreadsheet_id = m.group(1)

        sh = client.open_by_key(spreadsheet_id)
        ws = sh.sheet1
        records = ws.get_all_records()
        df = pd.DataFrame(records)

        required = {"Compétition", "URL"}
        if not required.issubset(set(df.columns)):
            st.error(f"Le Google Sheet doit contenir les colonnes {required}. Colonnes trouvées : {list(df.columns)}")
            return pd.DataFrame()

        return df
    except Exception as e:
        st.error(f"Erreur lecture Google Sheet : {e}")
        return pd.DataFrame()

# -----------------------
# Init driver (utilise le driver système)
# -----------------------
def init_driver(headless: bool = True):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # N'utilise pas webdriver-manager ici : on suppose geckodriver/firefox présents sur l'environnement
    driver = webdriver.Firefox(options=options)
    return driver

# -----------------------
# Scraper ElComparador (fonction basée sur tes extraits précédents)
# -----------------------
def scrape_elcomparador_competition(comp_url: str, selected_bookmakers: list, nb_matchs: int = 5, headless: bool = True) -> pd.DataFrame:
    """
    Scrape une page de compétition ElComparador et retourne un DataFrame long :
    colonnes = ['Match','Bookmaker','1','X','2','TRJ (%)'].
    selected_bookmakers : liste de display names e.g. ["Bet365","Codere",...]
    """
    # Lancer driver
    try:
        driver = init_driver(headless=headless)
    except Exception as e:
        st.error(f"Impossible d'initialiser Firefox (driver) : {e}")
        return pd.DataFrame()

    try:
        driver.get(comp_url)
    except Exception as e:
        driver.quit()
        st.error(f"Erreur accès URL {comp_url} : {e}")
        return pd.DataFrame()

    # attendre le rendu JS
    time.sleep(3)
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # normaliser sélection bookmakers en forme "Bet365" etc.
    selected_lower = [s.lower() for s in selected_bookmakers]

    match_divs = soup.find_all("div", id="fila_evento")
    if not match_divs:
        # Avertissement mais pas erreur bloquante
        st.warning("Aucun match trouvé sur la page (structure HTML différente).")
        return pd.DataFrame()

    # limiter
    match_divs = match_divs[:nb_matchs]

    for match_div in match_divs:
        teams_div = match_div.find("div", id="celda_evento_partido")
        if not teams_div:
            continue
        teams = " - ".join([t.strip() for t in teams_div.stripped_strings if "Estadísticas" not in t and "Pronósticos" not in t])
        if teams == "Evento":
            continue

        cuotas_divs = match_div.find_all("div", id="fila_cuotas")
        if len(cuotas_divs) < 3:
            home_odds = ["-"] * len(BOOKMAKERS_ORDER)
            draw_odds = ["-"] * len(BOOKMAKERS_ORDER)
            away_odds = ["-"] * len(BOOKMAKERS_ORDER)
        else:
            def extract_from_fila(fila):
                cells = fila.find_all("div", id="celda_cuotas")[1:]  # skip first label (apuesta)
                return [cell.get_text(strip=True) if cell.get_text(strip=True) else "-" for cell in cells]

            home_odds = extract_from_fila(cuotas_divs[0])
            draw_odds = extract_from_fila(cuotas_divs[1])
            away_odds = extract_from_fila(cuotas_divs[2])

        # associer par ordre global BOOKMAKERS_ORDER
        for i, bm_key in enumerate(BOOKMAKERS_ORDER):
            display_name = bm_key.capitalize()
            if display_name not in selected_bookmakers:
                continue

            h = home_odds[i] if i < len(home_odds) else "-"
            x = draw_odds[i] if i < len(draw_odds) else "-"
            a = away_odds[i] if i < len(away_odds) else "-"

            # calcul TRJ (en %) : TRJ = 1 / (1/h + 1/x + 1/a) -> *100
            trj_val = np.nan
            try:
                if h != "-" and x != "-" and a != "-":
                    h_f = float(h.replace(",", "."))
                    x_f = float(x.replace(",", "."))
                    a_f = float(a.replace(",", "."))
                    trj = 1.0 / (1.0/h_f + 1.0/x_f + 1.0/a_f)
                    trj_val = round(trj * 100, 2)
            except Exception:
                trj_val = np.nan

            rows.append({
                "Match": teams,
                "Bookmaker": display_name,
                "1": h,
                "X": x,
                "2": a,
                "TRJ (%)": trj_val
            })

    df = pd.DataFrame(rows)
    df["TRJ (%)"] = pd.to_numeric(df["TRJ (%)"], errors="coerce")  # s'assurer typage float (NaN si absent)
    return df

# -----------------------
# Helper affichage TRJ moyen (identique style part1)
# -----------------------
def display_average_trj(df: pd.DataFrame, sport: str):
    if df is None or df.empty:
        st.info(f"Aucune donnée disponible pour calculer le TRJ pour {sport}.")
        return
    df2 = df.copy()
    if "TRJ (%)" not in df2.columns:
        st.warning("Colonne 'TRJ (%)' introuvable dans le DataFrame.")
        return
    # calculer moyenne en ignorant NaN
    trj_mean = df2.groupby("Bookmaker")["TRJ (%)"].mean().reset_index()
    trj_mean.columns = ["Bookmaker", "Average TRJ (%)"]
    trj_mean["Average TRJ (%)"] = trj_mean["Average TRJ (%)"].round(2)
    trj_mean = trj_mean.sort_values(by="Average TRJ (%)", ascending=False).reset_index(drop=True)
    st.subheader(f"📊 Moyenne TRJ par opérateur - {sport}")
    st.dataframe(trj_mean)

# -----------------------
# UI principal (structure identique à part2)
# -----------------------
def main():
    st.sidebar.title("📌 Menu")

    menu_selection = st.sidebar.radio(
        "Choose a mode",
        ["🏠 Home", "⚽ Football"]  # pour l'instant seulement Football
    )

    if menu_selection == "🏠 Home":
        st.title("Welcome to the Betting Odds Scraper 🏠")
        st.write("Utilise la sidebar pour sélectionner un sport puis les compétitions à scraper (depuis Google Sheet).")

    elif menu_selection == "⚽ Football":
        sport = "Football"
        st.title(f"📊 {sport} Betting Odds Scraper (ElComparador)")

        # Charger compétitions depuis sheet
        competitions_df = load_competitions_from_sheet(GOOGLE_SHEET_URL)
        if competitions_df.empty:
            st.warning(f"Aucune compétition trouvée. Vérifie le Google Sheet et les secrets.")
            return

        # Multiselect des compétitions (colonne "Compétition")
        selected_competitions = st.multiselect("📌 Select competitions", competitions_df["Compétition"].tolist(), default=competitions_df["Compétition"].tolist()[:1])

        if selected_competitions:
            # Bookmakers (8 demandés)
            all_bookmakers = BOOKMAKERS_DISPLAY
            selected_bookmakers = st.multiselect("🎰 Select bookmakers", all_bookmakers, default=all_bookmakers)

            nb_matchs = st.slider("🔢 Number of matches per competition", 1, 30, 5)

            if st.button("🔍 Start scraping"):
                with st.spinner("Scraping in progress..."):
                    all_odds_df = pd.DataFrame()
                    progress = st.progress(0)
                    total = len(selected_competitions)
                    for idx, comp in enumerate(selected_competitions):
                        # récupérer URL depuis sheet
                        try:
                            comp_url = competitions_df.loc[competitions_df["Compétition"] == comp, "URL"].values[0]
                        except Exception:
                            st.error(f"URL introuvable pour la compétition {comp}. Vérifie le Google Sheet.")
                            continue

                        scraped_df = scrape_elcomparador_competition(
                            comp_url,
                            selected_bookmakers,
                            nb_matchs,
                            headless=True
                        )
                        if not scraped_df.empty:
                            all_odds_df = pd.concat([all_odds_df, scraped_df], ignore_index=True)
                        progress.progress((idx+1)/total)

                    progress.empty()

                    if not all_odds_df.empty:
                        # Afficher moyenne TRJ triée
                        display_average_trj(all_odds_df, sport)

                        st.subheader(f"📌 Retrieved {sport} Odds (détail)")
                        # Formater TRJ pour affichage (2 décimales ou '-')
                        df_display = all_odds_df.copy()
                        df_display["TRJ (%)"] = df_display["TRJ (%)"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
                        st.dataframe(df_display, use_container_width=True)

                        # CSV download (raw numeric)
                        csv = all_odds_df.to_csv(index=False).encode("utf-8")
                        st.download_button("📥 Télécharger CSV", csv, "elcomparador_odds.csv", "text/csv")
                    else:
                        st.info("Aucun odds récupéré.")
        else:
            st.info("Please select at least one competition to begin.")

if __name__ == "__main__":
    main()
