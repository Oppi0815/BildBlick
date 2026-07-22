# Änderungsprotokoll

Alle wesentlichen Änderungen an BildBlick werden in dieser Datei dokumentiert.

## Version 1.5.0

### Neu

- Ausgewählte Bilder verkleinert als JPEG-Kopien exportieren
- Frei wählbare maximale Breite und Höhe
- Einstellbare JPEG-Qualität
- Größenabschätzung vor dem Export
- Exportfortschritt und Abbruchmöglichkeit
- Wahlweise Übernahme der Aufnahmedaten
- GPS-Daten beim Export entfernen
- Einzelne Bilder mit F2, über das Menü oder per Rechtsklick umbenennen
- Erweiterte Diashow mit Pause und Fortsetzen per Leertaste
- Diashow nur mit markierten Bildern
- Zufällige Diashow-Reihenfolge
- Aufnahmeinformationen während der Diashow
- Sanfte Bildübergänge
- Automatisches Ausblenden des Mauszeigers im Vollbild

### Verbessert

- Erweiterte Statusleiste mit Aufnahmezeit, Kamera, Objektiv,
  Belichtungszeit, Blende, Brennweite und GPS-Daten
- Informativer Kopfbereich mit aktuellem Ordner und Bildanzahl
- Deutlich sichtbare rote Auswahlhaken im gesamten Programm
- Sichere Aktualisierung von Bildliste, Auswahl und Cache nach dem Umbenennen
- Exportdialog merkt die zuletzt verwendeten Einstellungen

## Version 1.4.0

### Neu

- Statusleiste mit Bildposition, Abmessungen, Dateigröße, ISO und Zoom
- Sortierung der Vorschaubilder nach Dateiname, Aufnahmedatum,
  Änderungsdatum und Dateigröße
- Aufsteigende und absteigende Sortierung
- Ordnernavigation mit Zurück, Vorwärts und übergeordnetem Ordner
- Bilder für die Anzeige nach links und rechts drehen
- Gedrehte Kopie speichern
- Drehung sicher im Original speichern
- Dreh- und Speicherfunktionen in den Kontextmenüs
- Aktuelles oder rechtsgeklicktes Bild im Dateimanager anzeigen

### Verbessert

- Breitere Navigationsschaltflächen für „Vorheriges Bild“ und
  „Nächstes Bild“
- Erhalt von Auswahl, Sortierung und Navigation bei verschiedenen Aktionen
- Kontextmenüs der großen Bildanzeige und der Vorschaubilder erweitert

## 1.3.0 – 22.07.2026

### Neu

- Zwei Bilder nebeneinander vergleichen, gemeinsam zoomen und verschieben.

## 1.2.1 – 22.07.2026

### Verbessert

- Beim Zoomen wird die aktuelle Vergrößerung kurz direkt über dem Bild
  eingeblendet.
- Die Zoomanzeige funktioniert in der normalen Bildansicht und im Vollbild.
- Bei „Bild einpassen“ wird die tatsächliche Vergrößerung angezeigt.
- Die Anzeige verschwindet nach kurzer Zeit automatisch.

## 1.2.0 – 21.07.2026

### Neu

- Größe der Vorschaubilder einstellbar und per Tastenkürzel veränderbar.
- Bilddateien und Ordner können beim Programmstart als Argument übergeben werden.
- Dadurch können Bilder direkt aus Nemo mit BildBlick geöffnet werden.

## 1.1.1 – 21.07.2026

### Verbessert

- Vorheriges Bild, Dateiname und Nächstes Bild werden jetzt platzsparend in einer gemeinsamen Zeile angezeigt.
- Der große Bildbereich erhält dadurch mehr vertikalen Platz.
- Lange Dateinamen werden kompakt dargestellt und vollständig als Tooltip angezeigt.

## [1.1.0] – 2026-07-21

### Neu

- Suche nach bytegenau identischen Bildern mit Größen-, SHA-256- und Inhaltsvergleich
- Gruppierte Duplikatanzeige mit Vorschaubildern und Speicherplatzübersicht
- Geschützte „Behalten“-Auswahl und sicheres Verschieben ausgewählter Duplikate in den Linux-Papierkorb
- Abbrechbare Duplikatsuche in einem eigenen Hintergrund-ThreadPool
- Anzeige der ISO-Empfindlichkeit in EXIF-Tooltips, einschließlich eingebettetem ExifIFD
- Interaktiv veränderbare und gespeicherte Spaltenbreiten im Duplikatdialog
- Zentralisierte Programmversion und neu gestalteter Über-Dialog

### Verbessert

- Portable Ermittlung des persönlichen Bilderordners
- Robuste Zwischenablageverarbeitung mit Wiedereintrittsschutz und Nemo-Unterstützung
- Deutlich erkennbare grüne Behalten- und rote Papierkorb-Markierungen
- Fehlerbehandlung und Rückmeldungen bei teilweise erfolgreichen Dateivorgängen

## [1.0.0]

- Erste Version mit Verzeichnisbaum, Vorschaubildern und Bildanzeige
- Zoom, Vollbild und Diashow
- Mehrfachauswahl sowie Kopieren, Ausschneiden und Einfügen
- Verschieben von Bildern in den Linux-Papierkorb
- EXIF-Metadaten in Vorschaubild-Tooltips
- Mehrere Farbschemata
