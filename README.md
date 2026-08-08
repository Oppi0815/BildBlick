<p align="center">
  <img src="assets/bildblick.png" alt="BildBlick-Logo" width="128" height="128">
</p>

# BildBlick

![BildBlick Screenshot](docs/bildblick-screenshot.png)

*BildBlick 1.12.0 unter Linux Mint*

**Version 1.12.0**

BildBlick ist ein schneller und komfortabler Bildbetrachter für Linux. Die Anwendung wurde unter Linux Mint entwickelt und getestet und verbindet eine übersichtliche Verzeichnisnavigation mit schnellen Vorschaubildern und praktischen Werkzeugen für die Bildverwaltung.

## Funktionen

- Verzeichnisbaum zur Navigation im Dateisystem
- Schnelle Vorschaubilder mit Metadaten-Cache
- Zoom, Originalgröße und Vollbildansicht
- Konfigurierbare Diashow
- Mehrfachauswahl von Bildern
- Größe der Vorschaubilder über einen Slider direkt unter der Vorschauliste
  verändern, mit Minus- und Plus-Schaltflächen sowie sofortiger, dauerhaft
  gespeicherter Anpassung
- Versteckte Dateien und Ordner bei Bedarf über **Ansicht** einblenden
- Kopieren, Ausschneiden und Einfügen, einschließlich Nemo-kompatibler Zwischenablage
- Sicheres Verschieben in den Linux-Papierkorb
- EXIF-Tooltips mit Abmessungen, Aufnahmedatum und ISO-Empfindlichkeit
- Farbschemata: System, Hell, Dunkel, Anthrazit und Warm
- Suche nach identischen Bildern mit sicherer Papierkorbauswahl

## PDF-Unterstützung

- PDF-Dateien erscheinen als Thumbnails; die erste Seite dient als Vorschau.
- PDFs öffnen direkt im normalen Bildbereich und behalten beim Zoom und bei
  „Bild auf Fenstergröße“ ihr Seitenverhältnis.
- Sichtbare Schaltflächen sowie `PageUp` und `PageDown` wechseln PDF-Seiten;
  die Anzeige lautet „Seite X von Y“.
- PDF-Dokumente funktionieren auch im Vollbild und können per Drag-and-drop
  geöffnet oder als lokale Datei-URL herausgezogen werden.
- Große mehrseitige PDFs werden bedarfsgerecht gerendert.

„Vorheriges Bild“ und „Nächstes Bild“ wechseln zwischen Dateien. „Vorherige
Seite“ und „Nächste Seite“ wechseln ausschließlich innerhalb der geöffneten
PDF. PDF-Bearbeitung, Textsuche und Textextraktion sind nicht enthalten.

## Drucken

- Einzelbilddruck über den nativen Qt-Druckdialog
- Mehrbilddruck und Kontaktabzug mit festen oder benutzerdefinierten Rastern
- Mehrseitige Druckvorschau mit Seitennavigation
- Druckprofile einschließlich eigener Benutzerprofile
- Kopf- und Fußzeilen mit freiem Text, Ordnername, Seitenzahl und Druckdatum
- PDF-Ausgabe über „In Datei drucken“
- Dateiname und Aufnahmedatum als Kontaktabzug-Beschriftung

### Mehrere Bilder drucken

1. Bilder markieren.
2. **Datei → Mehrere Bilder drucken …** oder **Kontaktabzug …** wählen.
3. Raster und Beschriftung wählen.
4. Vorschau prüfen.
5. **Weiter zum Druckdialog …** wählen.
6. Drucker oder **In Datei drucken** wählen.

## Unterstützte Dateiformate

BildBlick berücksichtigt JPEG (`.jpg`, `.jpeg`), PNG, WebP, BMP, GIF sowie TIFF (`.tif`, `.tiff`) und PDF (`.pdf`). Welche konkreten Bildvarianten dekodiert werden können, hängt zusätzlich von den in Pillow und Qt verfügbaren Bildformat-Plug-ins ab.

## Drag-and-drop

Bilddateien, PDFs und Ordner können aus Nemo direkt in BildBlick abgelegt werden. Bei einer Datei öffnet BildBlick ihren Ordner und zeigt die abgelegte Datei an. Mehrere Dateien aus demselben Ordner werden gemeinsam markiert; die zuerst abgelegte Datei wird angezeigt. Unterstützt werden die oben genannten Dateiformate.

### Bilder aus BildBlick herausziehen

Ein oder mehrere markierte Bilder oder PDFs lassen sich aus der Vorschauliste nach Nemo, auf den Schreibtisch oder als Anhang in ein Thunderbird-Verfassenfenster ziehen. BildBlick übergibt lokale Datei-URLs als Kopiervorgang; die Originale werden nicht verändert.

## Installation aus dem Quellcode

Voraussetzungen sind Python 3, `venv` und die üblichen Qt-Laufzeitbibliotheken der verwendeten Linux-Distribution.

```bash
git clone <repository-url>
cd BildBlick
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Start mit Python

```bash
source .venv/bin/activate
python bildbetrachter.py
```

## Eigenständige Anwendung bauen

Das Build-Skript verwendet die mitgelieferte PyInstaller-Spezifikation:

```bash
./build.sh
```

Das Ergebnis wird als `dist/BildBlick` erzeugt. Diese Binärdatei gehört nicht in das Git-Repository und kann separat als GitHub-Release-Datei veröffentlicht werden.

## Wichtige Tastenkürzel

| Taste | Funktion |
|---|---|
| `←` / `→` | Vorheriges beziehungsweise nächstes Bild |
| `PageUp` / `PageDown` | Vorherige beziehungsweise nächste Seite der geöffneten PDF |
| `Pos1` / `Ende` | Erstes beziehungsweise letztes Bild |
| `0` | Bild einpassen |
| `1` | Originalgröße |
| `F5` | Diashow starten oder stoppen |
| `F11` | Vollbild ein- oder ausschalten |
| `Strg+A` | Alle Bilder auswählen |
| `Strg+C` / `Strg+X` / `Strg+V` | Kopieren, Ausschneiden und Einfügen |
| `Entf` | Ausgewählte Bilder in den Papierkorb verschieben |
| `F1` | Hilfe öffnen |

## Sicherheit bei Dateivorgängen

BildBlick löscht Bilder nicht dauerhaft, sondern verschiebt sie mit Send2Trash in den Linux-Papierkorb. Vor Papierkorbaktionen ist eine Bestätigung erforderlich.

Die Duplikatsuche erkennt in der aktuellen Version ausschließlich bytegenau identische Dateien. Sie gruppiert zunächst nach Dateigröße, berechnet anschließend SHA-256-Hashes und bestätigt Treffer durch einen blockweisen Inhaltsvergleich. Ähnliche, verkleinerte oder neu komprimierte Bilder gelten nicht als Duplikate.

## Lizenz

BildBlick wird unter der [MIT-Lizenz](LICENSE) veröffentlicht. Hinweise zu verwendeten Bibliotheken enthält [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
