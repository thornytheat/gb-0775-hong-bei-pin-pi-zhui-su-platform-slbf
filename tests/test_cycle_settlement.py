from app.pipeline import compute


SOURCED = {
    'origins': 'origin,label,available,unit\nO1,产地一,1000,g\n',
    'jobs': 'work,label,measured,unit\nA,甲,100,g\nB,乙,50,g\nC,丙,20,g\n',
    'inputs': (
        'ticket,work,source_kind,source,quantity,unit\n'
        'I1,A,origin,O1,80,g\nI2,A,return,RT-B,20,g\n'
        'I3,B,origin,O1,30,g\nI4,B,return,RT-A,20,g\n'
        'I5,C,return,RT-A,20,g\n'
    ),
    'outputs': (
        'ticket,work,kind,gross,tare,unit\n'
        'PK-A,A,pack,50,0,g\nRT-A,A,return,50,0,g\n'
        'PK-B,B,pack,30,0,g\nRT-B,B,return,20,0,g\n'
        'PK-C,C,pack,20,0,g\n'
    ),
}


def test_originless_circle_clears_weight_but_stays_pending(dirty):
    settlement = dirty['balance']['cycle_settlements'][0]
    assert settlement['members'] == ['BA-09', 'BA-10']
    assert settlement['state'] == 'no_origin'
    assert not settlement['settled']
    assert settlement['weight_settled']
    assert settlement['internal_return_g'] == '100'
    assert dirty['lineage']['jobs']['BA-09']['codes'] == ['CYCLE']
    assert dirty['balance']['jobs']['BA-09']['pending_g'] == '50'
    assert dirty['packing']['returns']['RT-I']['available_g'] == '0'
    assert dirty['packing']['returns']['RT-J']['available_g'] == '0'


def test_sourced_circle_settles_origin_and_downstream_stock():
    result = compute(SOURCED)
    settlement = result['balance']['cycle_settlements'][0]
    assert settlement['settled'] and settlement['certified']
    assert settlement['external_origin_g'] == {'O1': '110'}
    assert result['lineage']['jobs']['A']['codes'] == []
    assert result['lineage']['jobs']['B']['codes'] == []
    assert result['packing']['packages']['PK-C']['origin_g'] == {'O1': '20'}
    rt_a = result['packing']['returns']['RT-A']
    assert (rt_a['drawn_g'], rt_a['available_g']) == ('40', '10')
    assert result['balance']['warehouse']['return_stock_g'] == '10'
    assert result['balance']['warehouse']['origin_used_g'] == '110'
    assert result['balance']['balanced']


def test_incomplete_ticket_blocks_whole_circle():
    files = {key: value for key, value in SOURCED.items()}
    files['inputs'] = SOURCED['inputs'].replace('I3,B,origin,O1,30,g\n', '')
    result = compute(files)
    settlement = result['balance']['cycle_settlements'][0]
    assert settlement['state'] == 'incomplete_evidence'
    assert not settlement['settled'] and not settlement['weight_settled']
    assert result['balance']['jobs']['A']['pending_g'] == '100'
    assert result['balance']['jobs']['B']['pending_g'] == '50'
    assert result['lineage']['jobs']['C']['codes'] == ['UPSTREAM_PENDING']


def test_completing_tickets_and_rerunning_does_not_double_count():
    incomplete = {key: value for key, value in SOURCED.items()}
    incomplete['inputs'] = SOURCED['inputs'].replace('I3,B,origin,O1,30,g\n', '')
    first = compute(incomplete)
    assert first['balance']['warehouse']['origin_used_g'] == '0'
    assert first['balance']['warehouse']['pending_g'] == '170'

    second = compute(SOURCED)
    third = compute(SOURCED)
    assert second['balance'] == third['balance']
    warehouse = second['balance']['warehouse']
    assert warehouse['origin_used_g'] == '110'
    assert warehouse['cycle_settled_return_g'] == '40'
    assert int(warehouse['origin_used_g']) == (
        int(warehouse['pack_g']) + int(warehouse['return_stock_g'])
    )
