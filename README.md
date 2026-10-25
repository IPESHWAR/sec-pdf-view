# Protected document

Local tools that turn the pictures in `images/` into an encrypted PDF and show those same pictures in a browser on this computer.

```
build_pdf.py           Build protected_document.pdf
generate_students.py   Create 6-digit student access codes
students.json          Names, codes, and server tokens
app.py                 Start the viewer (local, tunnel, or Vercel)
server.py              Viewer application
index.html             The viewer page (opened through the server)
pdfpages.py            In-memory PDF-to-PNG rendering
config.py              PDF password, bind address, image quality
imaging.py             Shared image loading
images/                Source pictures
```

Supported pictures: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`.

## Setup

From this folder, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Build the PDF

```powershell
python build_pdf.py
```

That reads `images/`, writes `protected_document.pdf`, and checks the lock before it finishes. The sample password is `123456`.

```powershell
python build_pdf.py --password "123456" --images images --output protected_document.pdf
```

Change the password in `config.py` (`USER_PASSWORD`), then build again. The viewer uses that same value.

`OWNER_PASSWORD` is a second secret. Keep it different from the user password. Readers that honor PDF flags turn printing, copying, and editing off for the user password, and the owner password is what lifts those flags.

## Student access codes

Each student gets a unique 6-digit code. Names and codes live in `students.json` (kept out of git). Generate a roster from this folder:

```powershell
python generate_students.py --count 50
python generate_students.py --count 100 --force
python generate_students.py --names roster.txt --append
```

`--names` reads one student name per line. Without that file, names are `Student 001` and so on. Edit the names in `students.json` before handing the codes out. Replacing the file invalidates sessions that are already open. The long `token` on each row stays on the server; students only type the 6-digit code.

## Start the viewer

```powershell
python app.py
```

Open the address it prints. On this computer that is http://127.0.0.1:5000. Phones and other computers on the same network use the local-network address it prints. The server listens on all interfaces, port 5000.

Share that server with the class through a public tunnel. Leave both commands running:

```powershell
python app.py
npx --yes localtunnel --port 5000
```

The tunnel prints an `https://` address. Give that address to the 50 students, with one code each from `students.json`. The address stays up while this computer and both commands stay running. Starting the tunnel again creates a new address.

## Deploy on Render

The folder includes `Procfile`, `students.json`, and `protected_document.pdf`. In Render, create a Web Service from this project. The start command is the Procfile:

```text
web: gunicorn app:app
```

Set the environment variable `SECRET_KEY` to a long random string. Render sets `PORT`; the app reads it. `students.json` and `protected_document.pdf` are ignored by git, so a deploy that only uploads committed files will not include them. Upload this folder directly, or remove those two lines from `.gitignore` before the first push.

## Deploy on Vercel

From this folder, after `npx vercel login`:

```powershell
npx vercel
```

Set a project environment variable named `SECRET_KEY` to a long random string before the first production deploy, then deploy again. The upload includes `protected_document.pdf` and `students.json`. It does not include the original pictures in `images/`.

Vercel runs the app as a short-lived function. A page render has to finish inside the plan's time limit, and a very large page image can be rejected. The tunnel above is the reliable way to give all 50 students the same address from this computer.

A student enters their code. The server then renders each PDF page to a PNG in memory and returns those bytes only. The browser draws them on a canvas and repeats a light gray "Rebin" diagonally across the page. The PDF file and its path are not sent to the browser, and page images are not written to disk.

Lock returns to the code screen. Restart `app.py` after you change `config.py`. New codes in `students.json` are picked up on the next sign-in without a restart.

## What each layer does

The PDF is AES-256 encrypted. A reader needs the user password to open the content. The file also stores permission flags that turn off printing, copying text and graphics, and modifying. Adobe Acrobat and other readers that follow those flags enforce them. The flags are not a second password: a tool that ignores permission bits can still print or copy after the file is unlocked. pypdf, which this project uses to write the file, is one of those tools.

The browser page asks this server for the pages. Until a student's code is accepted, the server does not send them. Pages are drawn only on a canvas: there is no PDF.js viewer, iframe, or image element. Right-click, text selection, dragging, Print Screen, Ctrl/Cmd+P, Ctrl/Cmd+S, Ctrl/Cmd+Shift+I (and the J/C inspector shortcuts), and F12 are blocked when the browser delivers those keys. Printing is styled as a blank page.

On a desktop or laptop, the page turns black as soon as the window blurs or the tab becomes hidden, including when a snip tool takes the foreground. On a phone or tablet, a tap does not black out the page. The canvas watermark is the word Rebin, in a light face at about 9% gray, rotated -30 degrees with wide gaps between repeats. `build_pdf.py` also burns Rebin into every PDF page.

The source files in `images/` are unchanged, and the viewer writes screen-sized copies under `cache/previews/`. Anyone who can open this folder can open those pictures directly. The encrypted PDF is the copy to move to another machine. Delete `cache/previews/` when you want those screen copies gone.

A web page cannot decide what Windows does with a window that is still in front. Snipping Tool, the system Print Screen handler, screen recording, and a camera pointed at the monitor can still capture it. Print Screen often never reaches the page, because Windows handles that key itself. The black overlay matters when the capture also takes focus away from this window.
