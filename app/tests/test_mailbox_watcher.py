from app.imap.mailbox_watcher import discover_mailboxes


def test_discover_mailboxes_includes_sent_folder():
    mailboxes = discover_mailboxes(["INBOX", "Bulk", "Sent", "Trash"])

    assert mailboxes == ["INBOX", "Bulk", "Sent"]
