"""Deterministic anchored search for wishes missed by random day sampling."""
from bisect import bisect_left,bisect_right
from collections import Counter
from nutrition import KEYS


def anchored_days(fixed,slots,values,recipes,targets,bounds,portions,strict,limits,max_results=24,max_checks=2_000_000,daily_limits=None):
    """Return (days, exhausted, checked). Exact within each anchor up to budget.

    Index the last dish by all four nutrients, then intersect via the narrowest
    permissible window. Never declare impossibility if the budget was exhausted.
    """
    results=[];seen=set();checks=0
    for position,choices in enumerate(slots):
        if fixed not in choices:continue
        a_pos,b_pos=[p for p in range(3) if p!=position]
        sorted_b={k:sorted((values[n][k],n) for n in slots[b_pos]) for k in KEYS} if strict else {}
        for a in slots[a_pos]:
            checks+=1
            if checks>max_checks:return results,False,checks-1
            candidates=slots[b_pos]
            if strict:
                windows=[]
                for key in KEYS:
                    lower,upper=daily_limits[key] if daily_limits else (targets[key]-bounds[key],targets[key]+bounds[key])
                    minimum=lower/portions-values[fixed][key]-values[a][key]
                    maximum=upper/portions-values[fixed][key]-values[a][key]
                    ordered=sorted_b[key]
                    lo=bisect_left(ordered,(minimum-1e-8,-1))
                    hi=bisect_right(ordered,(maximum+1e-8,float('inf')))
                    windows.append((hi-lo,key,lo,hi))
                width,key,lo,hi=min(windows)
                if width==0:continue
                candidates=(n for _,n in sorted_b[key][lo:hi])
            for b in candidates:
                checks+=1
                if checks>max_checks:return results,False,checks-1
                day=[None]*3;day[position]=fixed;day[a_pos]=a;day[b_pos]=b;day=tuple(day)
                if day in seen:continue
                seen.add(day)
                if strict and not all((daily_limits[k][0]-1e-8<=sum(values[n][k] for n in day)*portions<=daily_limits[k][1]+1e-8) if daily_limits else abs(sum(values[n][k] for n in day)*portions-targets[k])<=bounds[k]+1e-8 for k in KEYS):continue
                counts=Counter(recipes[n].database_id for n in day)
                if any(counts[db]>quota for db,quota in limits.items()):continue
                results.append(day)
                if len(results)>=max_results:return results,False,checks
    return results,True,checks


def anchor_diagnostic(fixed,slots,values,recipes,targets,bounds,portions,strict):
    if not strict:return 'Проверьте дневные сочетания и количество блюд из каждой базы.'
    ranges={k:[] for k in KEYS}
    for pos,choices in enumerate(slots):
        if fixed not in choices:continue
        other=[j for j in range(3) if j!=pos]
        for k in KEYS:
            ranges[k].append(((values[fixed][k]+sum(min(values[n][k] for n in slots[j]) for j in other))*portions,
                              (values[fixed][k]+sum(max(values[n][k] for n in slots[j]) for j in other))*portions))
    labels={'kcal':'Калории, ккал','protein':'Белки, г','fat':'Жиры, г','carbs':'Углеводы, г'}
    conflicts=[]
    for k,variants in ranges.items():
        if variants and all(high<targets[k]-bounds[k]-1e-8 or low>targets[k]+bounds[k]+1e-8 for low,high in variants):
            low=min(v[0] for v in variants);high=max(v[1] for v in variants)
            conflicts.append(f'{labels[k]}: с этим блюдом возможно {low:.1f}–{high:.1f}, требуется {targets[k]-bounds[k]:.1f}–{targets[k]+bounds[k]:.1f}.')
    if conflicts:return '\n'.join(conflicts)
    return 'Отдельные диапазоны КБЖУ пересекаются с целями, но подходящее сочетание должно удовлетворять всем четырём одновременно и квотам баз.'
