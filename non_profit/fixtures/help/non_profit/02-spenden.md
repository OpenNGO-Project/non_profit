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
4. Ordnen Sie bei Bedarf eine aktive **Donation Campaign** zu.
5. Speichern und übermitteln Sie die Donation.
6. Erfassen Sie die Zahlung über **Actions → Create Payment Entry** oder lassen
   Sie einen verifizierten Zahlungsanbieter die Zahlung autorisieren.

## Kampagnen nutzen

Kampagnen bündeln mehrere Spenden zu einem Fundraising-Ziel. Hinterlegen Sie Namen, Zeitraum und Zielbetrag. Danach können Spenden der Kampagne zugeordnet und Auswertungen einfacher gelesen werden.

## Verdankung und Spendenbescheinigung

Bei einer bezahlten Donation verwenden Sie **Actions → Verdankung senden** oder
**Als extern verdankt markieren**. Beide Wege pflegen `thank_you_sent` und die
Auditfelder. Eine Verdankung ist keine Steuerbescheinigung.

Für eine **Donation Receipt** wählen Sie Donor und Geschäftsjahr und dann
**Actions → Spenden aus Geschäftsjahr hinzufügen**. Alternativ erzeugt die
Listenaktion **Jährliche Spendenbescheinigungen erstellen** Entwürfe je Donor.
Nur übermittelte, bezahlte und noch nicht anderweitig belegte Spenden im
gewählten Zeitraum sind zulässig. Prüfen, übermitteln und senden Sie den Entwurf
erst danach.

> **Rechtlicher Hinweis:** Das mitgelieferte Format **Donation Receipt DE**
> enthält deutsches Steuerrecht. Das Standardland Schweiz ändert diesen Text
> nicht. Verwenden Sie es nicht als Schweizer Steuerbescheinigung. Lassen Sie
> vor Produktivbetrieb eine rechtlich freigegebene lokale Vorlage erstellen.

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
Prüfen Sie Pflichtfelder, Einwilligung, eine aktive Kampagne und, falls angezeigt, den CAPTCHA-Schritt.
