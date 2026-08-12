# Änderungsprotokoll

Alle wesentlichen Änderungen an BildBlick werden in dieser Datei dokumentiert.

## 1.16.0

### Neu

- Einblendbares Bildinformationen-/EXIF-Panel direkt neben der Bildansicht.
- Kompakte Datei-, Kamera- und Aufnahmeinformationen sowie aufklappbare
  Ansicht „Alle Metadaten“ für EXIF, GPS, IPTC und weitere unterstützte Daten.

### Verbessert

- Leere Metadatenfelder und -gruppen werden ausgeblendet; XMP bleibt von der
  Oberfläche ausgeschlossen und MakerNotes werden sicher dargestellt.
- Linke Seitenleiste aufgeräumt; die drei Navigationspfeile über dem
  Verzeichnisbaum entfallen.

## 1.15.1

### Behoben

- Mehrbild-Druckvorschau unter Linux korrigiert.
- HiDPI/DPR-Skalierungsfehler im Preview behoben.
- Footer-Texte in der Mehrbildvorschau wieder sichtbar.
- Aufnahmedatum im Mehrbilddruck korrigiert.
- Drucktextfarbe unabhängig vom UI-Theme gemacht.
- Checkboxen im Light/System-Modus besser sichtbar.

### Verbessert

- Dateiname/Aufnahmedatum aktivieren automatisch Kontaktabzug.
- Titeltext aktiviert automatisch Kopfzeile.
- PDF-Weblinks und `mailto:`-Links anklickbar.
- Interne PDF-Sprünge unterstützt.
- Hand-Cursor über PDF-Links.
- Nur sichere URL-Schemata `http`, `https` und `mailto` werden extern geöffnet.

## 1.15.0 – Neues Drucksystem und macOS-App

### Neu

- Eigener WYSIWYG-Einzelbilddruck und eigener Mehrbilddruck.
- Gemeinsame PagePlan-/Renderer-Architektur für Vorschau, PDF und Druck.
- PDF-Export sowie Einzelbild- und Mehrbildprofile einschließlich Randlos-Profil.
- Interaktive Einzelbild-Positionierung und Größenänderung.
- Mehrbild-Reihenfolge per Drag-and-drop und Kontaktabzug im normalen Mehrbilddialog.
- Light-/Dark-Mode-Unterstützung der Druckdialoge.
- Native macOS-App `BildBlick.app` mit App-Icon.

### Verbessert

- **Drucken …** und **Mehrere Bilder drucken …** verwenden ausschließlich das neue Drucksystem.
- Alte parallele WYSIWYG-/Legacy-Menüpunkte und der Legacy-Druckcode wurden entfernt.
- Druckvorschau, PDF und echter Druck verwenden dieselbe Layoutgrundlage.
- Druckdialoge sind unter macOS klarer und konsistenter dargestellt.

## 1.14.1 – Korrigierte PDF-Seitennavigation

### Behoben

- PDF-Seitensteuerung überlappt nicht mehr mit Dateinavigation und Dateiname.
- Sichtbare PDF-Seitennavigation im Vollbild.
- Klare Trennung zwischen Dateiwechsel und PDF-Seitenwechsel.
- Kein leerer Bereich bei normalen Bildern.
- Kein leerer Bereich bei einseitigen PDFs.

### Verbessert

- Eigene zentrierte PDF-Seitenleiste unter der Dokumentansicht.
- Kompakte Schaltflächen für vorherige und nächste PDF-Seite.
- Tooltips und barrierefreie Bezeichnungen für PDF-Seitenbuttons.
- Korrekte Aktivierung und Deaktivierung an erster und letzter PDF-Seite.
- Zuverlässige Aktualisierung bei PDF → Bild → PDF.

## 1.14.0 – Kompakte Bildnavigation

### Neu

- Kompakte Datei-Navigation direkt unter den Vorschaubildern mit kleinen
  Schaltflächen für die vorherige und nächste Datei.
- Der Dateiname und die PDF-Seitennavigation befinden sich in derselben
  kompakten Steuerzeile.

### Verbessert

- Bildname, Vor- und Zurücknavigation sind in die Steuerzeile unter den
  Vorschaubildern umgezogen.
- Die bisherige Leiste unter dem Bild entfällt; dadurch steht mehr Höhe für
  die Bilddarstellung zur Verfügung.
- Der Thumbnail-Größenregler sowie seine Minus-/Plus-Schaltflächen sind
  flacher und kompakter.
- Ordnerbaum, Thumbnail-Liste, Statusleiste und Splitter-Griffe wirken ruhiger
  und sind für helle wie dunkle Oberflächen besser abgestimmt.
- Vorheriges und nächstes Bild haben Tooltips und barrierefreie Namen.
- Die kompakte Navigation gilt unter Linux und macOS; die automatische
  PDF-Vorschau bleibt auf macOS beschränkt.

## 1.13.2 – Flacher Vorschauregler

### Verbessert

- Die kompakte Steuerung für Vorschaubilder ist nun auch vertikal deutlich
  flacher und fügt sich zurückhaltender in die Seitenleiste ein.

## 1.13.1 – Dezente Vorschausteuerung

### Verbessert

- Der Regler für die Vorschaubildgröße ist kompakt und mittig angeordnet,
  bleibt aber mit Minus- und Plus-Schaltfläche vollständig bedienbar.

## 1.13.0 – Überarbeitete Oberfläche

### Verbessert

- Die Hauptansicht wirkt ruhiger und klarer: strukturierte Seitenleiste,
  großzügigere Listen, abgerundete Auswahlflächen und schlankere Navigation.
- Bedienelemente und Statusleiste sind optisch einheitlicher und besser
  proportioniert — auch mit dem macOS-Systemfarbschema.

## 1.12.2 – PDF-Vorschau auf macOS

### Neu

- Ein direkt im Finder geöffnetes PDF wird auf macOS in einer großen Vorschau
  ohne Verzeichnis- und Dateileisten angezeigt.
- Escape oder „Ansicht → PDF-Vorschau verlassen“ stellt die Dateileisten wieder
  her.

## 1.12.1 – PDF-Start und Darstellungsqualität

### Neu

- Kommandozeilenparameter `--fullscreen`.
- Eigener Linux-Desktop-Starter für PDFs.
- PDF-Dateien können als Standardprogramm direkt mit BildBlick geöffnet werden.
- Optionaler automatischer Vollbildstart für PDFs.

### Verbessert

- Die erste PDF-Seite wird bereits beim ersten Öffnen scharf dargestellt.
- Thumbnail-Rendering und Großansicht verwenden getrennte Rendergrößen.
- Zu kleine PDF-Renderbilder werden nicht mehr für die Großansicht verwendet.
- Nach Layout- oder Größenänderungen wird bei Bedarf höher aufgelöst neu gerendert.
- Die PDF-Darstellung berücksichtigt die benötigte Rendergröße.
- Start über Nemo und per Doppelklick funktioniert zuverlässig.
- `--fullscreen` verwendet den vorhandenen Vollbildmodus; Escape und F11
  können ihn weiterhin verlassen.

## 1.12.0 – PDF-Unterstützung

### Neu

- PDF-Dateien erscheinen in der normalen Thumbnail-Liste.
- Die erste PDF-Seite wird als Vorschaubild dargestellt.
- PDF-Dokumente werden direkt im Großbildbereich geöffnet.
- Sichtbare Navigation durch PDF-Seiten mit Anzeige „Seite X von Y“.
- PageUp und PageDown zur PDF-Seitennavigation.
- Zoom und „Bild auf Fenstergröße“ funktionieren auch für PDFs.
- PDF-Dateien können per Drag-and-drop geöffnet und herausgezogen werden.

### Verbessert

- Das Seitenverhältnis von PDF-Seiten bleibt erhalten; Hoch- und Querformat
  werden korrekt dargestellt.
- Große und mehrseitige PDFs lassen sich zuverlässig durchblättern.
- PDF-Seiten werden auf weißem Hintergrund korrekt zusammengesetzt;
  transparente oder komplexe Inhalte erscheinen nicht mehr zu dunkel.
- Vollbild funktioniert für Bilder und PDFs und blendet Navigations- sowie
  Thumbnail-Bereiche vollständig aus.
- Beschädigte, leere und passwortgeschützte PDFs werden ohne Absturz behandelt.
- PDF-Rendering ist vom normalen Bildladen getrennt; QtPdf wird im
  PyInstaller-Build berücksichtigt.

### Einschränkungen

- PDF-Bearbeitung ist nicht enthalten.
- Es gibt keine Textsuche oder Textextraktion.
- PDF-Formulare und Annotationen werden nicht unterstützt.
- Die vorhandenen Druckfunktionen wurden nicht auf vollständigen
  PDF-Dokumentdruck erweitert.

## 1.11.0 – Versteckte Dateien und Ordner

### Neu

- Menüpunkt „Ansicht → Versteckte Dateien und Ordner anzeigen“.
- Versteckte Dateien und Verzeichnisse sind standardmäßig ausgeblendet und
  lassen sich jederzeit ein- oder ausblenden.
- Die gewählte Einstellung wird dauerhaft gespeichert.

### Verbessert

- Übersichtlichere Ordnernavigation.
- `.DS_Store` und AppleDouble-Dateien wie `._Bild.jpg` werden standardmäßig
  ausgeblendet.
- Einheitliche Filterung in Ordnerbaum und Thumbnail-Ansicht.
- Normale Dateien auf Netzwerkfreigaben bleiben unverändert zugänglich.

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
