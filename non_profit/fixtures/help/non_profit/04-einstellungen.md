---
title: Einstellungen
slug: non-profit-einstellungen
category: Non Profit
level: Intermediate
---

# Non Profit Einstellungen

Die **Non Profit Settings** verbinden die fachlichen Non-Profit-Prozesse mit ERPNext: Standardfirma, Standardwerte und weitere Vorgaben für Spenden und Mitgliedschaften.

![Non Profit Settings im Desk](/assets/non_profit/images/help/02-non-profit-settings.png)

## Wann prüfen?

Prüfen Sie die Einstellungen nach der Installation, nach einem Firmenwechsel oder wenn Spenden bzw. Mitgliedschaften nicht mit der erwarteten Firma oder den erwarteten Defaults erstellt werden.

## Wichtige Punkte

- **Membership Invoicing**: Abrechnungszyklus, Firma, Rechnungs-/Zahlungskonten
  sowie automatische Legacy-Rechnungs- und Payment-Entry-Optionen.
- **Membership Acknowledgement**: Versand-Schalter, Membership Print Format,
  optionales Invoice Print Format und Email Template.
- **Donation Settings**: Donation Company, Default Donor Type, automatische
  Payment Entries, Debit-/Zahlungskonto und Standard-Dankesmail.
- **Default Receipt Country**: Datenstandard; ändert nicht den Rechtstext eines
  Print Formats.
- **Creation User**: technischer Benutzer für automatisierte Dokumente.
- **Major Donor Threshold**: Schwelle für automatische Grossspender-Markierung.

**Stale Interaction Days** und **Lapsed Major Months** sind reserviert und lösen
derzeit keine Automatik aus.

## Häufige Fragen

**Eine Spende wird der falschen Firma zugeordnet.**
Prüfen Sie zuerst die Non Profit Settings und danach die Einstellungen der kundenspezifischen App, falls eine solche App verwendet wird.

**Soll ich kundenspezifisches Branding hier pflegen?**
Nein. Branding, Briefpapier und Demo-Oberflächen gehören in die jeweilige Kunden- oder Präsentations-App.

**Kann ich Donation Receipt DE in der Schweiz verwenden?**
Nicht ohne fachliche Freigabe. Die Vorlage enthält deutsches Steuerrecht. Das
Feld **Default Receipt Country** lokalisiert die Vorlage nicht.
