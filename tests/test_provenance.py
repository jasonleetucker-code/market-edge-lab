from edge_lab.provenance import bytes_sha256, payload_sha256, shape_fingerprint, shape_paths


def test_payload_hash_ignores_key_order():
    assert payload_sha256({"a": 1, "b": 2}) == payload_sha256({"b": 2, "a": 1})


def test_raw_bytes_hash_is_exact():
    assert bytes_sha256(b'{"a":1}') != bytes_sha256(b'{"a": 1}')


def test_shape_ignores_values_and_array_length():
    one = {"markets": [{"ticker": "A", "yes_bid": "0.40"}]}
    many = {"markets": [{"ticker": "B", "yes_bid": "0.10"}, {"ticker": "C", "yes_bid": "0.90"}]}
    assert shape_fingerprint(one) == shape_fingerprint(many)


def test_shape_detects_new_field_and_type_change():
    base = {"markets": [{"ticker": "A", "yes_bid": "0.40"}]}
    added = {"markets": [{"ticker": "A", "yes_bid": "0.40", "new": 1}]}
    retyped = {"markets": [{"ticker": "A", "yes_bid": 0.40}]}
    assert shape_fingerprint(base) != shape_fingerprint(added)
    assert shape_fingerprint(base) != shape_fingerprint(retyped)
    assert "$.markets[].yes_bid:number" in shape_paths(retyped)
