#!/usr/bin/env python3
"""
LEX Service - Generator descrieri FULL FEED
Procesează toate produsele, output Excel
"""

import pandas as pd
import openai
import json
import os
import time
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── CONFIG ──────────────────────────────────────────────────
API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = "gpt-4o-mini"
MAX_WORKERS = 15          # requesturi paralele
SAVE_EVERY = 100          # salvează progresul la fiecare N produse
INPUT_FILE = "ll-products.xlsx"
OUTPUT_FILE = "ll-products-output.xlsx"
PROGRESS_FILE = "ll-products-progress.json"
ESHOP_FILE = "eshop.csv"
STOCK_FILE = "data_export-18.xlsx"

client = openai.OpenAI(api_key=API_KEY)

SYSTEM_PROMPT = """Ești un copywriter expert pentru un magazin online de piese de schimb și accesorii pentru electrocasnice (LexService.ro).

Trebuie să generezi:
1. DENUMIRE NOUĂ - scurtă, clară, profesională (max 80 caractere). Fără ghilimele.
2. TITLU META - optimizat SEO, max 60 caractere, include cuvinte cheie relevante
3. DESCRIERE META - optimizată SEO, max 155 caractere, call-to-action subtil
4. DESCRIERE HTML - bine structurată, informativă, cu secțiune de SOLUȚII
5. FAQ HTML - 5 întrebări și 5 răspunsuri relevante

REGULI pentru DESCRIERE HTML:
- Folosește <h3>, <p>, <ul>, <li>, <strong> pentru structură
- Secțiuni obligatorii:
  * Descriere generală (ce este produsul, pentru ce se folosește)
  * Specificații tehnice principale
  * SOLUȚII - descrie CE PROBLEMĂ REZOLVĂ acest produs (ex: "Mașina de spălat nu mai centrifughează?", "Aspiratorul nu mai aspiră corespunzător?"). Ajută clientul să înțeleagă DE CE are nevoie de produs și ce defecțiune/problemă remediază.
  * Beneficii (economisire, durabilitate, performanță restaurată)
  * Compatibilitate (maxim 3-5 modele exemplu)
- Menționează WhatsApp: 0751 055 805 pentru verificare compatibilitate
- Tonul: profesional, de încredere, orientat spre client
- Lungime: 200-350 cuvinte

REGULI pentru FAQ:
- 5 întrebări și 5 răspunsuri relevante pentru produs
- Întrebări practice: compatibilitate, montaj, simptome defecțiune, garanție, livrare
- Răspunsuri clare, utile, care inspiră încredere
- Format HTML: fiecare FAQ într-un <div class="faq-item"><h4>Întrebarea</h4><p>Răspunsul</p></div>

Răspunde STRICT în format JSON:
{
  "denumire_noua": "...",
  "titlu_meta": "...",
  "descriere_meta": "...",
  "descriere_html": "<HTML structurat cu descriere + soluții>",
  "faq_html": "<HTML cu 5 div-uri faq-item>"
}"""


def generate_one(idx, nume, descriere, categorie):
    """Generează conținut nou pentru un singur produs"""
    descriere_scurta = descriere[:1500] if len(descriere) > 1500 else descriere

    user_prompt = f"""Produs de procesat:

DENUMIRE ACTUALĂ: {nume}
CATEGORIE: {categorie}
DESCRIERE ACTUALĂ:
{descriere_scurta}

Generează denumirea, titlul meta, descrierea meta, descrierea HTML cu soluții și FAQ-ul în format JSON."""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=1500
            )

            content = response.choices[0].message.content
            content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)

            # Verifică că toate câmpurile există
            for key in ["denumire_noua", "titlu_meta", "descriere_meta", "descriere_html", "faq_html"]:
                if key not in result:
                    result[key] = ""

            return idx, result

        except json.JSONDecodeError:
            # Încearcă să extragă JSON-ul din răspuns
            try:
                start = content.index('{')
                end = content.rindex('}') + 1
                result = json.loads(content[start:end])
                for key in ["denumire_noua", "titlu_meta", "descriere_meta", "descriere_html", "faq_html"]:
                    if key not in result:
                        result[key] = ""
                return idx, result
            except:
                if attempt < 2:
                    time.sleep(1)
                    continue

        except openai.RateLimitError:
            wait = 2 ** (attempt + 1)
            print(f"   ⚠️  Rate limit la #{idx+1}, aștept {wait}s...")
            time.sleep(wait)
            continue

        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"   ❌ Eroare la #{idx+1}: {e}")

    return idx, {
        "denumire_noua": nume,
        "titlu_meta": "",
        "descriere_meta": "",
        "descriere_html": "",
        "faq_html": ""
    }


def load_progress():
    """Încarcă progresul salvat anterior"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_progress(results_dict):
    """Salvează progresul curent"""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results_dict, f, ensure_ascii=False)


def main():
    print("=" * 60)
    print("LEX Service - Generator Descrieri FULL FEED")
    print(f"Model: {MODEL} | Workers: {MAX_WORKERS}")
    print("=" * 60)

    # Citește datele
    print("\n📂 Citesc fișierul Excel...")
    df = pd.read_excel(INPUT_FILE)
    total = len(df)
    print(f"   Total produse: {total}")

    # Încarcă progresul anterior
    progress = load_progress()
    done_count = len(progress)
    if done_count > 0:
        print(f"   ♻️  Progres anterior găsit: {done_count}/{total} produse deja procesate")
        print(f"   Continuăm de unde am rămas...")

    # Pregătește lista de produse de procesat
    tasks = []
    for idx, row in df.iterrows():
        if str(idx) in progress:
            continue
        nume = str(row['Nume produs']) if pd.notna(row['Nume produs']) else ""
        descriere = str(row['Descriere produs']) if pd.notna(row['Descriere produs']) else ""
        categorie = str(row['Categorie principala']) if pd.notna(row['Categorie principala']) else ""
        tasks.append((idx, nume, descriere, categorie))

    remaining = len(tasks)
    print(f"   De procesat: {remaining} produse\n")

    if remaining == 0:
        print("   Toate produsele sunt deja procesate!")
    else:
        start_time = time.time()
        processed = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for idx, nume, descriere, categorie in tasks:
                future = executor.submit(generate_one, idx, nume, descriere, categorie)
                futures[future] = idx

            for future in as_completed(futures):
                idx, result = future.result()
                progress[str(idx)] = result
                processed += 1

                if not result.get('denumire_noua') or result['denumire_noua'].startswith('[EROARE]'):
                    errors += 1

                # Progress bar
                total_done = done_count + processed
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (remaining - processed) / rate if rate > 0 else 0
                eta_min = int(eta // 60)
                eta_sec = int(eta % 60)

                pct = total_done / total * 100
                bar_len = 30
                filled = int(bar_len * total_done / total)
                bar = '█' * filled + '░' * (bar_len - filled)

                print(f"\r   [{bar}] {pct:.1f}% | {total_done}/{total} | "
                      f"{rate:.1f} prod/s | ETA: {eta_min}m{eta_sec:02d}s | "
                      f"Erori: {errors}", end='', flush=True)

                # Salvează progres periodic
                if processed % SAVE_EVERY == 0:
                    save_progress(progress)

        # Salvează progresul final
        save_progress(progress)
        elapsed_total = time.time() - start_time
        print(f"\n\n   ⏱  Timp total procesare: {int(elapsed_total//60)}m{int(elapsed_total%60):02d}s")
        print(f"   📊 Rată medie: {processed/elapsed_total:.1f} produse/secundă")

    # ─── Încarcă statusurile din eshop ────────────────────────
    eshop_map = {}
    if os.path.exists(ESHOP_FILE):
        df_eshop = pd.read_csv(ESHOP_FILE)
        eshop_map = dict(zip(df_eshop['Cod produs - SKU'].astype(str), df_eshop['StocE']))
        print(f"\n📦 Eshop: {len(eshop_map)} produse cu status încărcate din {ESHOP_FILE}")
    else:
        print(f"\n⚠️  Fișierul {ESHOP_FILE} nu a fost găsit, coloana StocE va fi goală")

    # ─── Încarcă stocul din data_export ──────────────────────
    stock_map = {}
    if os.path.exists(STOCK_FILE):
        df_stock = pd.read_excel(STOCK_FILE)
        stock_map = dict(zip(df_stock['Cod produs - SKU'].astype(str), df_stock['Stoc']))
        print(f"📊 Stoc: {len(stock_map)} produse cu stoc încărcate din {STOCK_FILE}")
    else:
        print(f"\n⚠️  Fișierul {STOCK_FILE} nu a fost găsit, coloana Stoc va fi goală")

    # ─── Construiește Excel-ul final ─────────────────────────
    print(f"\n📝 Generez Excel-ul final...")

    # Pre-încarcă TOATE numele originale din input pentru deduplicare completă
    all_original_names = set()
    for _, row in df.iterrows():
        orig = str(row['Nume produs']).strip() if pd.notna(row.get('Nume produs')) else ""
        if orig:
            all_original_names.add(orig)
    print(f"   📋 {len(all_original_names)} nume originale unice încărcate pentru deduplicare")

    output_rows = []
    seen_names = set(all_original_names)  # pornește cu TOATE numele originale

    for idx, row in df.iterrows():
        result = progress.get(str(idx), {})

        sku = str(row['Cod produs - SKU']) if pd.notna(row.get('Cod produs - SKU')) else ""
        sku_uzn = f"{sku}-UZN" if sku else ""

        pret = row.get('Pret produs')
        pret_val = pret if pd.notna(pret) else ""

        stoc_eshop = eshop_map.get(sku, "")
        stoc_val = stock_map.get(sku, "")

        # ─── Deduplicare denumiri (vs originale + vs alte generate) ───
        denumire = result.get('denumire_noua', '')
        if denumire:
            if denumire in seen_names:
                # Prima încercare: adaugă SKU
                denumire_cu_sku = f"{denumire} - {sku}"
                if denumire_cu_sku not in seen_names:
                    denumire = denumire_cu_sku
                else:
                    # Dacă și cu SKU e duplicat, adaugă counter
                    counter = 2
                    while f"{denumire} - {sku} ({counter})" in seen_names:
                        counter += 1
                    denumire = f"{denumire} - {sku} ({counter})"
            seen_names.add(denumire)

        output_rows.append({
            'Cod produs - SKU': sku_uzn,
            'Denumire noua': denumire,
            'Titlu meta': result.get('titlu_meta', ''),
            'Descriere meta': result.get('descriere_meta', ''),
            'Descriere HTML': result.get('descriere_html', ''),
            'FAQ HTML': result.get('faq_html', ''),
            'Pret produs': pret_val,
            'URL imagine principala': str(row['URL imagine principala']) if pd.notna(row.get('URL imagine principala')) else "",
            'Imagini secundare': "",
            'StocE': stoc_eshop,
            'Stoc': stoc_val,
            'Categorie principala': str(row['Categorie principala']) if pd.notna(row.get('Categorie principala')) else "",
            'Denumire originala': str(row['Nume produs']) if pd.notna(row.get('Nume produs')) else "",
        })

    df_out = pd.DataFrame(output_rows)

    # Verifică duplicate rămase
    dupes = df_out['Denumire noua'].duplicated().sum()
    print(f"   🔍 Denumiri duplicate rămase: {dupes}")

    df_out.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')

    print(f"\n✅ DONE! Output salvat în: {OUTPUT_FILE}")
    print(f"   Total rânduri: {len(df_out)}")
    print(f"   Coloane: {', '.join(df_out.columns)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
