"""Run: python make_zip.py   Builds jowar-lambda.zip from the files in this folder.
Any replay_*.json you add (for example replay_sep2025.json) is included automatically."""
import glob, zipfile
files = ["lambda_function.py", "scoring.py", "corridors.json", "tides.json", "replays.json"] + sorted(glob.glob("replay_*.json"))
with zipfile.ZipFile("jowar-lambda.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in dict.fromkeys(files):
        z.write(f)
print("zipped:", zipfile.ZipFile("jowar-lambda.zip").namelist())
