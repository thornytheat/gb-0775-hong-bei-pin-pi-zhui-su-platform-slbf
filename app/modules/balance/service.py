from fractions import Fraction

from .stock import stock


def verify_mass(intake, trace, packing):
    jobs={}
    for work, recipe in trace['jobs'].items():
        dispatch=packing['jobs'][work]
        incoming=Fraction(recipe['input_g'])
        remaining=Fraction(dispatch['hold_g'])+Fraction(dispatch['return_g'])
        delta=incoming-remaining-sum(Fraction(dispatch[key]) for key in ('pack_g','loss_g','pending_g'))
        origin_delta=incoming-Fraction(dispatch['pending_g'])-sum(Fraction(g) for g in recipe['composition_g'].values())
        jobs[work]=dict(input_g=str(incoming),pack_g=dispatch['pack_g'],loss_g=dispatch['loss_g'],
                        remainder_g=str(remaining),pending_g=dispatch['pending_g'],delta_g=str(delta),
                        origin_delta_g=str(origin_delta),codes=recipe['codes'],job_line=recipe['job_line'],
                        cycle_path=recipe.get('cycle_path',[]),
                        cycle_status=recipe.get('cycle_status'),
                        cycle_settled=recipe.get('cycle_settled',False),
                        cycle_closed=recipe.get('cycle_closed',False),
                        cycle_settlement=recipe.get('cycle_settlement'))
    line_delta={key:row['records']-row['accepted']-row['isolated'] for key,row in intake['files'].items()}
    warehouse=stock(trace,packing)
    settlements=settle_cycle_returns(trace,packing)
    warehouse['cycle_settled_return_g']=str(sum(
        (Fraction(row['weight_settled_return_g']) for row in settlements
         if row.get('weight_settled_return_g') is not None),Fraction()))
    warehouse['cycle_certified_return_g']=str(sum(
        (Fraction(row['settled_return_g']) for row in settlements if row['settled']),Fraction()))
    warehouse['cycle_return_stock_g']=str(sum(
        (Fraction(row.get('return_remaining_g','0')) for row in settlements),Fraction()))
    warehouse['cycle_pending_g']=str(sum(
        (Fraction(row['circle_batch_g']) for row in settlements if not row['settled']),Fraction()))
    packages={key:Fraction(row['g'])-sum(Fraction(g) for g in row['origin_g'].values()) for key,row in packing['packages'].items()}
    balanced=warehouse['balanced'] and not any(line_delta.values()) and not any(packages.values())
    balanced=balanced and all(row['delta_g']==row['origin_delta_g']=='0' for row in jobs.values())
    return dict(jobs=jobs,warehouse=warehouse,cycle_settlements=settlements,cycles=settlements,
                cycle_returns=settlements,settlements=settlements,
                closed_cycles=[row for row in settlements if row['settled']],
                pending_cycles=[row for row in settlements if not row['settled']],
                line_delta=line_delta,balanced=balanced,
                package_delta_g={key:str(value) for key,value in packages.items()})


def settle_cycle_returns(trace, packing=None):
    """Add coupon and stock movements to the lineage cycle settlements."""
    if packing is None and isinstance(trace,dict) and 'lineage' in trace and 'packing' in trace:
        packing=trace['packing']
        trace=trace['lineage']
    settlements=trace.get('cycle_settlements',[]) if isinstance(trace,dict) else []
    returns=packing.get('returns',{}) if isinstance(packing,dict) else {}
    for settlement in settlements:
        members=set(settlement['members'])
        coupon_rows=[row for row in returns.values() if row['work'] in members]
        coupon_total=sum((Fraction(row['g']) for row in coupon_rows),Fraction())
        drawn_total=sum((Fraction(row['drawn_g']) for row in coupon_rows),Fraction())
        remaining_total=sum((Fraction(row['available_g']) for row in coupon_rows
                             if row['available_g'] is not None),Fraction())
        internal_total=Fraction(settlement['internal_return_g'])
        circle_used=internal_total if settlement.get('weight_settled') else Fraction()
        downstream_total=drawn_total-circle_used
        settlement.update(return_coupon_g=str(coupon_total),return_drawn_g=str(drawn_total),
                          claimed_circle_g=str(internal_total),circle_used_g=str(circle_used),
                          downstream_used_g=str(downstream_total),
                          return_remaining_g=str(remaining_total),available_g=str(remaining_total),
                          remaining_g=str(remaining_total),stock_g=str(remaining_total))
    return settlements


settle_cycles = settle_cycle_returns
