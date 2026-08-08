# Änderungsprotokoll

Alle wesentlichen Änderungen an BildBlick werden in dieser Datei dokumentiert.

## 1.10.0 – Anpassbare Vorschaubildgröße

### Neu

- Horizontaler Größenregler unterhalb der Vorschaubilder.
- Vorschaubilder während der Benutzung vergrößern und verkleinern.
- Minus- und Plus-Schaltflächen zur schrittweisen Größenänderung.
- Unmittelbare Aktualisierung der Thumbnail-Darstellung.
- Speicherung der gewählten Vorschaubildgröße über QSettings und
  Wiederherstellung beim Programmstart.

### Verbessert

- Auswahl und aktuelles Bild bleiben bei Größenänderungen erhalten.
- Das Seitenverhältnis der Vorschaubilder bleibt unverändert.
- Gültige Mindest- und Höchstwerte sowie robuste Behandlung ungültiger
  gespeicherter Werte.
- Darstellung für helle und dunkle Oberfläche angepasst.

## 1.9.0 – Drag-and-drop und macOS-Vorbereitung

*Veröffentlicht am 08.08.2026*

### Neu

- Bilder und Ordner lassen sich per Drag-and-drop in BildBlick öffnen.
- Mehrere abgelegte Bilder werden gemeinsam markiert; das erste Bild wird
  automatisch angezeigt.
- Markierte Bilder lassen sich aus BildBlick herausziehen, auch mehrere
  gleichzeitig nach Nemo, auf den Schreibtisch oder in kompatible Programme.
- Dateiübergabe erfolgt als lokale Datei-URLs; E-Mail-Anhänge per Drag-and-drop
  werden beispielsweise von Thunderbird unterstützt.
- macOS-Dateiöffnungsereignisse und plattformabhängige Vorbereitung.

### Verbessert

- Mehrfachauswahl bleibt beim Drag-out vollständig erhalten und die Reihenfolge
  der gezogenen Bilder ist stabil.
- Drag-out kopiert Dateien, statt sie zu verschieben; Drag-in und Drag-out
  beeinflussen Copy & Paste nicht.
- Ungültige oder nicht mehr vorhandene Dateien werden robust behandelt.

## 1.8.0 – Mehrbilddruck und Kontaktabzug

*Veröffentlicht am 07.08.2026*

### Neu

- Drucken des aktuell angezeigten Bildes über den nativen Qt-Druckdialog
- Hoch- und Querformat, Druckertreiber-Papierformate einschließlich A4 und A6,
  automatische und manuelle Bilddrehung sowie PDF-Ausgabe
- Mehrbilddruck und Kontaktabzug mit 1, 2, 4, 6, 9, 16 oder 32 Bildern pro
  Seite sowie frei wählbaren Zeilen und Spalten
- Frei einstellbare Seitenränder und Bildabstände
- Kontaktabzug-Beschriftungen mit Dateiname und Aufnahmedatum aus EXIF- oder
  Dateidaten
- Mehrseitige Druckvorschau mit Seitennavigation und Seitenzahlen
- Druckprofile, einschließlich eigener Profile zum Speichern, Laden,
  Überschreiben und Löschen, sowie automatischer Anzeige
  „Benutzerdefiniert“
- Kopfzeilen mit freiem Text oder aktuellem Ordnernamen
- Fußzeilen mit Ordnername, Seitenzahl und Druckdatum

### Verbessert

- Deutlich kleinere PDF-Dateien durch bedarfsgerechte Verkleinerung der
  Druckbilder
- Vorschau lädt nur die für die aktuelle Seite benötigten Bilder
- Reale Layoutvalidierung anhand der tatsächlichen Druckfläche
- Bessere Behandlung kleiner Kontaktabzugzellen sowie langer Datei- und
  Ordnernamen
- Vollständige Vorschauseite wird in das Vorschaufenster eingepasst
- Mehrbilddruckdialog öffnet standardmäßig ohne unnötige Scrollbalken
- Profil- und Druckdialoge sind im hellen Systemdesign wieder gut lesbar
- Gemeinsame Layoutberechnung für Vorschau und Ausdruck

### Technisch

- Zentrale `MultiImagePrintSettings`-Konfiguration
- Eigene Profilpersistenz mit UUID und QSettings
- Gemeinsame Zeichenlogik für Kopf- und Fußzeilen
- Automatisierte Layout- und Profiltests
- Keine neuen externen Laufzeitabhängigkeiten

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
