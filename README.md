<p align="center">
  <img src="assets/bildblick.png" alt="BildBlick-Logo" width="128" height="128">
</p>

# BildBlick

![BildBlick Screenshot](docs/bildblick-screenshot.png)

*BildBlick 1.9.0 unter Linux Mint*

**Version 1.9.0**

BildBlick ist ein schneller und komfortabler Bildbetrachter für Linux. Die Anwendung wurde unter Linux Mint entwickelt und getestet und verbindet eine übersichtliche Verzeichnisnavigation mit schnellen Vorschaubildern und praktischen Werkzeugen für die Bildverwaltung.

## Funktionen

- Verzeichnisbaum zur Navigation im Dateisystem
- Schnelle Vorschaubilder mit Metadaten-Cache
- Zoom, Originalgröße und Vollbildansicht
- Konfigurierbare Diashow
- Mehrfachauswahl von Bildern
- Kopieren, Ausschneiden und Einfügen, einschließlich Nemo-kompatibler Zwischenablage
- Sicheres Verschieben in den Linux-Papierkorb
- EXIF-Tooltips mit Abmessungen, Aufnahmedatum und ISO-Empfindlichkeit
- Farbschemata: System, Hell, Dunkel, Anthrazit und Warm
- Suche nach identischen Bildern mit sicherer Papierkorbauswahl

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

## Unterstützte Bildformate

BildBlick berücksichtigt JPEG (`.jpg`, `.jpeg`), PNG, WebP, BMP, GIF sowie TIFF (`.tif`, `.tiff`). Welche konkreten Varianten dekodiert werden können, hängt zusätzlich von den in Pillow und Qt verfügbaren Bildformat-Plug-ins ab.

## Drag-and-drop

Bilddateien und Ordner können aus Nemo direkt in BildBlick abgelegt werden. Bei einer Bilddatei öffnet BildBlick ihren Ordner und zeigt das abgelegte Bild an. Mehrere Bilder aus demselben Ordner werden gemeinsam markiert; das zuerst abgelegte Bild wird angezeigt. Unterstützt werden ausschließlich die oben genannten Bildformate.

### Bilder aus BildBlick herausziehen

Ein oder mehrere markierte Bilder lassen sich aus der Vorschauliste nach Nemo, auf den Schreibtisch oder als Anhang in ein Thunderbird-Verfassenfenster ziehen. BildBlick übergibt lokale Datei-URLs als Kopiervorgang; die Originale werden nicht verändert.

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
