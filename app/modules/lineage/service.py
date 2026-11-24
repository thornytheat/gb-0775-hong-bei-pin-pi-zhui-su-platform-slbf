from collections import defaultdict
from fractions import Fraction
from graphlib import TopologicalSorter

from .cycles import find_cycles
from .mix import blend
from .settle import solve_loop_composition


def trace(supply, limits):
    jobs, coupons=supply['jobs'],supply['return_lots']
    grouped=defaultdict(list)
    edges={work:set() for work in jobs}
    for row in supply['inputs']:
        work=row['work']
        grouped[work].append(row)
        if row['source_kind']=='return':
            edges[work].add(coupons[row['source']]['work'])
    loops=find_cycles(edges)
    loop_of={member:index for index,loop in enumerate(loops) for member in loop['members']}
    units={work:work for work in jobs}
    for index in range(len(loops)):
        unit=('cycle',index)
        for work in loops[index]['members']:
            units[work]=unit
    predecessors={}
    for work in jobs:
        unit=units[work]
        predecessors.setdefault(unit,set())
        for parent in edges[work]:
            parent_unit=units[parent]
            if parent_unit!=unit:
                predecessors[unit].add(parent_unit)
    result={}
    settlements=[]
    for unit in TopologicalSorter(predecessors).static_order():
        if not (isinstance(unit,tuple) and unit[0]=='cycle'):
            work=unit
            accepted=sum((Fraction(row['g']) for row in grouped[work]),Fraction())
            warnings=base_codes(work,accepted,loop_of,limits,supply,jobs)
            unresolved=unresolved_parents(work,edges,result)
            if unresolved:
                warnings.append('UPSTREAM_PENDING')
            mix, feed_rows=({},[]) if warnings else blend(grouped[work],coupons,result)
            result[work]=row_result(work,jobs,accepted,warnings,mix,feed_rows,loops,loop_of,unresolved,
                                    grouped,supply)
            continue
        cycle_index=unit[1]
        loop=loops[cycle_index]
        members=loop['members']
        member_set=set(members)
        accepted={work:sum((Fraction(row['g']) for row in grouped[work]),Fraction()) for work in members}
        code_map={work:base_codes(work,accepted[work],loop_of,limits,supply,jobs) for work in members}
        external_parents=sorted({parent for work in members for parent in edges[work]
                                 if parent not in member_set})
        unresolved=sorted(parent for parent in external_parents if result[parent]['codes'])
        evidence_failed={work:codes for work,codes in code_map.items()
                         if any(code!='CYCLE' for code in codes)}
        internal_rows=[feed for work in members for feed in grouped[work]
                       if feed['source_kind']=='return'
                       and coupons[feed['source']]['work'] in member_set]
        internal_g=sum((Fraction(feed['g']) for feed in internal_rows),Fraction())
        internal_tickets=sorted(feed['id'] for feed in internal_rows)
        ticket_g={feed['id']:feed['g'] for feed in sorted(internal_rows,key=lambda row:row['id'])}
        cycle_coupons=sorted(coupon for coupon,row in coupons.items() if row['work'] in member_set)
        batch_g=sum((Fraction(jobs[work]['g']) for work in members),Fraction())
        settlement=dict(id=f'CYCLE-{cycle_index+1:02d}',members=members,path=loop['path'],
                        settled=False,status='pending',state='evidence_pending',reason='CYCLE',
                        blockers=evidence_failed,upstream_pending=unresolved,
                        internal_return_g=str(internal_g),settled_return_g='0',
                        circle_batch_g=str(batch_g),settled_batch_g='0',settled_g='0',
                        external_origin_g={},origin_g={},composition_g={},
                        internal_tickets=internal_tickets,ticket_g=ticket_g,
                        settled_tickets=[],coupons=cycle_coupons)
        can_settle=not evidence_failed and not unresolved
        # A clean but originless SCC is necessarily a closed mass loop.  Its
        # weights can be cleared, while its origin/proof status stays pending.
        weight_settled=False
        compositions={}
        external={}
        if can_settle:
            try:
                ordered,fraction_parts,external=solve_loop_composition(
                    member_set,grouped,jobs,coupons,result)
                external_total=sum(external.values(),Fraction())
                if external_total==0:
                    can_settle=False
                    weight_settled=True
                    settlement.update(state='no_origin',reason='CYCLE_NO_ORIGIN',
                                      weight_settled=True,
                                      weight_settled_return_g=str(internal_g),
                                      settled_return_g=str(internal_g))
                else:
                    valid=all(all(value>=0 for value in parts.values())
                              and sum(parts.values(),Fraction())==Fraction(jobs[work]['g'])
                              for work,parts in fraction_parts.items())
                    if not valid:
                        raise ZeroDivisionError('循环产地克重不符合重量守恒')
                    compositions={work:{key:str(value) for key,value in parts.items()}
                                  for work,parts in fraction_parts.items()}
            except (ZeroDivisionError,ValueError):
                can_settle=False
                settlement.update(state='unresolvable',reason='CYCLE_UNRESOLVED')
        elif evidence_failed:
            settlement.update(state='incomplete_evidence',reason='TICKETS_INCOMPLETE')
        else:
            settlement.update(state='upstream_pending',reason='UPSTREAM_PENDING')
        if can_settle:
            for work in members:
                result[work]=row_result(work,jobs,accepted[work],[],compositions.get(work,{}),[],
                                        loops,loop_of,[],grouped,supply,settlement_id=settlement['id'])
            for work in members:
                mix,feed_rows=blend(grouped[work],coupons,result)
                result[work]['composition_g']=mix
                result[work]['lots']=feed_rows
            for work in members:
                result[work]['cycle_settled']=True
                result[work]['cycle_closed']=True
                result[work]['cycle_weight_settled']=True
                result[work]['cycle_status']='settled'
            total_composition=defaultdict(Fraction)
            for work in members:
                for origin,value in result[work]['composition_g'].items():
                    total_composition[origin]+=Fraction(value)
            external_text={key:str(value) for key,value in sorted(external.items())}
            gross_text={key:str(value) for key,value in sorted(total_composition.items())}
            settlement.update(settled=True,status='settled',state='settled',reason=None,
                              blockers={},upstream_pending=[],weight_settled=True,
                              weight_settled_return_g=str(internal_g),
                              settled_return_g=str(internal_g),settled_g=str(internal_g),
                              settled_batch_g=str(batch_g),
                              external_origin_g=external_text,origin_g=external_text,
                              composition_g=external_text,gross_composition_g=gross_text)
        else:
            for work in members:
                warnings=code_map[work]
                work_unresolved=[parent for parent in unresolved
                                 if parent in edges[work] and result[parent]['codes']]
                result[work]=row_result(work,jobs,accepted[work],warnings,{},[],loops,loop_of,
                                        work_unresolved,grouped,supply,
                                        settlement_id=settlement['id'])
                result[work]['cycle_settled']=False
                result[work]['cycle_closed']=False
                result[work]['cycle_status']=settlement['state']
                result[work]['cycle_weight_settled']=weight_settled
            settlement['weight_settled']=weight_settled
            if weight_settled:
                settlement.setdefault('weight_settled_return_g',str(internal_g))
        settlement['certified']=settlement['settled']
        settlement['pending']=not settlement['settled']
        settlement['closed']=bool(settlement.get('weight_settled'))
        if settlement['closed']:
            settlement['settled_tickets']=list(internal_tickets)
        settlements.append(settlement)
    settlements.sort(key=lambda row:row['members'])
    return dict(jobs=result,cycles=loops,cycle_settlements=settlements,
                cycle_returns=settlements,settlements=settlements,
                certified=sum(not row['codes'] for row in result.values()))


def base_codes(work,accepted,loop_of,limits,supply,jobs):
    warnings=[]
    if work in loop_of:
        warnings.append('CYCLE')
    if work in supply['by_input_issue']:
        warnings.append('INPUT_DISPUTE')
    if limits[work]['code']:
        warnings.append(limits[work]['code'])
    if accepted!=Fraction(jobs[work]['g']):
        warnings.append('INTAKE_MISMATCH')
    return warnings


def unresolved_parents(work,edges,result):
    return sorted(parent for parent in edges[work]
                  if parent in result and result[parent]['codes'])


def row_result(work,jobs,accepted,warnings,mix,feed_rows,loops,loop_of,unresolved,grouped,supply,
               settlement_id=None):
    loop_index=loop_of.get(work)
    path=loops[loop_index]['path'] if loop_index is not None else []
    row=dict(work=work,input_g=jobs[work]['g'],admitted_g=str(accepted),codes=warnings,
             lots=feed_rows,composition_g=mix,job_line=jobs[work]['line'],cycle_path=path,
             upstream_pending=unresolved,reported_inputs=grouped[work],
             input_issues=supply['by_input_issue'].get(work,[]))
    if settlement_id is not None:
        row['cycle_settlement']=settlement_id
    return row
