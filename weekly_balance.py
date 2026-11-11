"""Bounded beam search for seven days with a joint nutrition budget."""
from collections import Counter
from nutrition import KEYS


def daily_bounds(targets,kcal_spread=.3,macro_spread=.5,protein_floor=.75):
    return {k:(targets[k]*(max(protein_floor,1-macro_spread) if k=='protein' else 1-(kcal_spread if k=='kcal' else macro_spread)),
               targets[k]*(1+(kcal_spread if k=='kcal' else macro_spread))) for k in KEYS}


def balanced_week(candidates,values,recipes,targets,bounds,portions,tokens,limits,minima,capacities,rng,enforce=True,width=64):
    """Return indices of day candidates; None means search exhausted, not impossible.

    Preserve coverage and exact database counts, retain several nutrient budgets
    at each step. Unknown nutrition never enters a controlled weekly plan.
    """
    totals=[tuple(sum(values[n][k] for n in c[0])*portions for k in KEYS) for c in candidates]
    target=tuple(targets[k] for k in KEYS)
    low=tuple(max(0,targets[k]-bounds[k])*7 for k in KEYS)
    high=tuple((targets[k]+bounds[k])*7 for k in KEYS)
    def day_cost(i):return sum(((totals[i][k]-target[k])/max(target[k],1))**2 for k in range(4))
    # Include extremes and wishes so a near-target-only pool cannot erase
    # the dishes needed to compensate a compulsory high/low day.
    chosen=set(sorted(range(len(candidates)),key=day_cost)[:128])
    chosen.update(rng.sample(range(len(candidates)),min(128,len(candidates))))
    for k in range(4):
        ordered=sorted(range(len(candidates)),key=lambda i:totals[i][k])
        chosen.update(ordered[:24]);chosen.update(ordered[-24:])
    for token in sorted(tokens):
        chosen.update(sorted((i for i,c in enumerate(candidates) if token in c[1]),key=day_cost)[:16])
    patterns={}
    for i,c in enumerate(candidates):
        pattern=tuple(c[3][db] for db in sorted(limits))
        patterns.setdefault(pattern,[]).append(i)
    for group in patterns.values():chosen.update(sorted(group,key=day_cost)[:16])
    pool=sorted(chosen)
    minimum=tuple(min(totals[i][k] for i in pool) for k in range(4))
    maximum=tuple(max(totals[i][k] for i in pool) for k in range(4))
    costs={i:day_cost(i) for i in pool}
    # score, path, summed nutrition, uncovered wishes, database counts, usage, daily cost
    states=[(0,(),(0.,)*4,frozenset(tokens),Counter(),Counter(),0.)]
    for position in range(7):
        left=6-position;expanded={}
        for _,path,summed,uncovered,counts,usage,daily_cost in states:
            for i in pool:
                day,cover,_,dbcounts=candidates[i]
                new_counts=counts+dbcounts
                if any(not minima[db]*left<=quota-new_counts[db]<=capacities[db]*left for db,quota in limits.items()):continue
                if sum(quota-new_counts[db] for db,quota in limits.items())>left*3:continue
                needed=uncovered-cover
                if sum(t[0]=='recipe' for t in needed)>left*3:continue
                if not left and needed:continue
                nutrient_sum=tuple(summed[k]+totals[i][k] for k in range(4))
                if enforce and any(nutrient_sum[k]+minimum[k]*left>high[k]+1e-8 or nutrient_sum[k]+maximum[k]*left<low[k]-1e-8 for k in range(4)):continue
                if enforce and not left and any(not low[k]-1e-8<=nutrient_sum[k]<=high[k]+1e-8 for k in range(4)):continue
                average_error=sum(((nutrient_sum[k]/(position+1)-target[k])/max(target[k],1))**2 for k in range(4))
                deviation=sum((max(0,low[k]-nutrient_sum[k],nutrient_sum[k]-high[k])/max(target[k]*7,1))**2 for k in range(4)) if not left else 0
                new_usage=usage+Counter(day)
                cost=daily_cost+costs[i]
                score=1000*len(needed)+100*average_error+10000*deviation+5*cost+.0005*sum(v*v for v in new_usage.values())
                # Keep distinct budgets, coverage and quota patterns. Fine buckets
                # retain opposite sides of the target while bounding memory.
                signature=(needed,tuple(new_counts[db] for db in sorted(limits)),tuple(round(nutrient_sum[k]/max(target[k]*.002, .01)) for k in range(4)))
                old=expanded.get(signature)
                if old is None or score<old[0]:expanded[signature]=(score,path+(i,),nutrient_sum,needed,new_counts,new_usage,cost)
        if not expanded:return None
        states=sorted(expanded.values(),key=lambda s:s[0])[:width]
    return states[0][1] if states else None
