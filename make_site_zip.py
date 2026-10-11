"""Run: python make_site_zip.py   Builds site.zip (the web pages and app.js, plus any photos in img/) for Amplify or S3."""
import glob, zipfile
files = ["index.html", "app.js", "privacy.html", "terms.html"] + sorted(glob.glob("img/*.jpg"))
with zipfile.ZipFile("site.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f)
print("zipped:", zipfile.ZipFile("site.zip").namelist())
