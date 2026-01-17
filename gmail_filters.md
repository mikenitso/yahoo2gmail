# Gmail Filters

## Updates (combined: list mail + shipping + banking alerts)

Has the words:

```
(list-id: OR precedence:bulk OR list-unsubscribe: OR "Auto-Submitted: auto-generated" OR
(from:(@ups.com OR @fedex.com OR @usps.gov OR @dhl.com) AND
(subject:("Ship Notification" OR "Shipment" OR "Tracking" OR "Delivery" OR "Out for Delivery" OR "Delivery Confirmation"))) OR
(from:(noreply OR "no-reply" OR alerts OR notifications) AND
(subject:("statement" OR "payment" OR "due" OR "transaction" OR "purchase" OR "card" OR "account" OR "alert" OR "security" OR "verification" OR "fraud" OR "credit score" OR "FICO"))))
```

Categorize as: **Updates**
