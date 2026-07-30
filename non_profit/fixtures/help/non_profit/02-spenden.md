---
title: Spenden und Kampagnen
slug: non-profit-spenden
category: Non Profit
level: Beginner
---

# Spenden und Kampagnen

Spenden werden über **Donation** erfasst und optional einer **Donation Campaign** zugeordnet. Der Donor hält die Stammdaten der spendenden Person oder Organisation.

![Donation Liste im Desk](/assets/non_profit/images/help/03-donation-list.png)

## Spende erfassen

1. Legen Sie den Donor über den Erstellungsdialog aus einem **Contact**, einem
   **Customer** oder beiden an. Die E-Mail gehört zum verknüpften Customer bzw.
   Contact, nicht als eigenes Feld zum Donor.
2. Öffnen Sie **Donation** und wählen Sie **Neu**.
3. Wählen Sie Donor und Firma und erfassen Sie Betrag, Datum und Zahlungsart.
4. Ordnen Sie bei Bedarf eine aktive **Donation Campaign** zu. Für öffentliche
   Spenden muss deren Kostenstelle aktiv, ein Blatt und derselben Firma wie die
   Donation zugeordnet sein.
5. Speichern und übermitteln Sie die Donation.
6. Erfassen Sie die Zahlung über **Actions → Create Payment Entry** oder lassen
   Sie einen verifizierten Zahlungsanbieter die Zahlung autorisieren.

Bei installierter Good-Connector-Bankanbindung erhält eine übermittelte Donation
eine 27-stellige QR-Referenz. Mit der bankseitig ausgegebenen QR-IBAN auf dem
Schweizer Spendenbeleg kann eine eindeutige gebuchte Zahlung automatisch als
Payment Entry zugeordnet werden. Keine oder mehrere passende Spenden/Rechnungen
bleiben in der Bank Transaction mit **Review** zur manuellen Prüfung.
Die automatische Zuordnung unterstützt nur die Firmenwährung; Bankkonto und
Spender-Debitorenkonto müssen dieselbe Währung verwenden. Fremdwährungsfälle
bleiben zur manuellen Prüfung offen.

## Kampagnen nutzen

Kampagnen bündeln mehrere Spenden zu einem Fundraising-Ziel. Hinterlegen Sie Namen, Zeitraum und Zielbetrag. Danach können Spenden der Kampagne zugeordnet und Auswertungen einfacher gelesen werden.

## Verdankung und Spendenbescheinigung

Bei einer bezahlten Donation verwenden Sie **Actions → Verdankung senden** oder
**Als extern verdankt markieren**. Beide Wege pflegen `thank_you_sent` und die
Auditfelder. Eine Verdankung ist keine Steuerbescheinigung.

Für eine **Donation Receipt** wählen Sie Donor und Geschäftsjahr und dann
**Actions → Spenden aus Geschäftsjahr hinzufügen**. Alternativ erzeugt die
Listenaktion **Jährliche Spendenbescheinigungen erstellen** einen
Hintergrundauftrag. Er verarbeitet höchstens 200 sichtbare Spenden pro Lauf und
gruppiert Entwürfe nach Firma, Firmenwährung, Donor, Land und Zeitraum. Reicht
eine Gruppe über die 200er-Grenze hinaus, ergänzen Folgeläufe denselben gesperrten
Entwurf, statt eine zweite Bescheinigung anzulegen.
Nur übermittelte, bezahlte und noch nicht anderweitig belegte Spenden im
gewählten Zeitraum sind zulässig. Prüfen, übermitteln und senden Sie den Entwurf
erst danach.

> **Rechtlicher Hinweis:** Das mitgelieferte Format **Donation Receipt DE**
> enthält deutsches Steuerrecht. Das Standardland Schweiz ändert diesen Text
> nicht. Verwenden Sie es nicht als Schweizer Steuerbescheinigung. Lassen Sie
> vor Produktivbetrieb eine rechtlich freigegebene lokale Vorlage erstellen und
> wählen Sie diese in **Non Profit Settings → Approved Swiss Donation Receipt
> Print Format**. Der Schweizer Versand lehnt **Donation Receipt DE** ab und
> benötigt eindeutige vollständige Absender- und Empfängeradressen.

> **Währungshinweis:** Die generische öffentliche `/donate`-Seite und das
> Standard-Dankesmail zeigen EUR; der Schweizer QR-Spendenbeleg zeigt CHF. Diese
> Labels werden nicht aus einer Donation-Währung abgeleitet. Verwenden Sie
> produktiv nur einen lokal freigegebenen, einheitlichen Währungsflow.

## Häufige Fragen

**Eine Spende hat keinen Donor.**
Prüfen Sie, ob die Person oder Organisation bereits als Donor existiert. Wenn nicht, legen Sie zuerst den Donor an und verbinden danach die Spende.

**Die Kampagnensumme stimmt nicht.**
Prüfen Sie, ob alle Spenden der richtigen Kampagne zugeordnet sind und ob nur gültige bzw. bezahlte Spenden in der Auswertung berücksichtigt werden.

**Das öffentliche Spendenformular lehnt eine Eingabe ab.**
Prüfen Sie Pflichtfelder, Einwilligung, eine aktive Kampagne und den CAPTCHA-Schritt. Wenn das Laden des CAPTCHA fehlschlägt, bleibt die Schaltfläche zur Übermittlung gesperrt; verwenden Sie **Erneut versuchen**. Wenn das Formular auf eine fehlende CAPTCHA-Konfiguration hinweist, müssen in Good Connector sowohl Site Key als auch Secret gepflegt werden; ohne diese Konfiguration bleibt die Übermittlung gesperrt.
