import os
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI

# ------------------- LOAD ENV -------------------
load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# ------------------- FASTAPI SETUP -------------------
app = FastAPI(title="LLM Data Quality Checker", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")


# ------------------- LLM CALL -------------------
def call_llm(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b:free",
            messages=[
                {"role": "system", "content": "You are a professional data quality analyst."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=1200
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ LLM Error: {e}"


# ------------------- ANALYSIS ROUTE -------------------
@app.post("/analyze_csv/")
async def analyze_csv(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")

    try:
        df = pd.read_csv(file.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading CSV: {e}")

    original_rows = len(df)
    if original_rows > 5000:
        df = df.sample(5000, random_state=42)

    report = f"File Name: {file.filename}\n"
    report += f"Total Rows: {original_rows}\n"
    report += f"Columns: {len(df.columns)}\n\n"

    missing_report = df.isnull().mean() * 100
    report += "Missing Values (% per column):\n" + missing_report.to_string() + "\n\n"

    dup = df.duplicated().sum()
    report += f"Duplicate Rows: {dup}\n\n"

    report += "Data Types:\n" + df.dtypes.to_string() + "\n\n"

    num_cols = df.select_dtypes(include=["int64", "float64"]).columns
    if len(num_cols) > 0:
        stats = df[num_cols].agg(["mean", "std"])
        report += "Numeric Summary:\n" + stats.to_string() + "\n\n"

    prompt = (
        "You are a data quality expert. Summarize this raw report clearly in markdown for a professional data-quality dashboard. "
        "Use well-formatted markdown tables with pipes (|) and proper headers. "
        "Include full numeric summaries, then finish with a section titled '🚀 3 Actionable Improvements'. "
        "Render that section as a markdown table with these exact headers:\n"
        "| S.No | Recommendation | Why it matters | How to implement |\n"
        "Number the S.No column as 1, 2, and 3. "
        "Keep the style professional and stop the output after the final table.\n\n"
        f"{report}"
    )




    summary = call_llm(prompt)

    avg_missing = missing_report.mean()
    score = 100 - (avg_missing * 0.5) - (dup * 0.1)
    score = max(0, min(100, round(score, 2)))

    return JSONResponse({
        "file_name": file.filename,
        "rows_original": int(original_rows),
        "columns": int(len(df.columns)),
        "data_quality_score": score,
        "data_quality_summary": summary
    })
