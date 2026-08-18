from backend.cloud import platform_service as ps


def test_cloud_backup_history_scopes_queries_to_selected_org(monkeypatch):
    queries = []

    def fake_select(table, query, **_kwargs):
        queries.append((table, query))
        if table == 'businesses':
            return [{'id': '11111111-1111-1111-1111-111111111111'}]
        return [{'id': 'backup-1', 'business_id': '11111111-1111-1111-1111-111111111111'}]

    monkeypatch.setattr(ps, 'service_select_strict', fake_select)

    rows = ps.list_backups_for_org('org-1', limit=500)

    assert rows == [{'id': 'backup-1', 'business_id': '11111111-1111-1111-1111-111111111111'}]
    assert queries[0][0] == 'businesses'
    assert 'org_id=eq.org-1' in queries[0][1]
    assert queries[1][0] == 'backups'
    assert 'business_id=in.(11111111-1111-1111-1111-111111111111)' in queries[1][1]
    assert 'limit=100' in queries[1][1]


def test_cloud_backup_history_returns_empty_when_org_has_no_businesses(monkeypatch):
    monkeypatch.setattr(ps, 'service_select_strict', lambda *_args, **_kwargs: [])

    assert ps.list_backups_for_org('org-without-business') == []
