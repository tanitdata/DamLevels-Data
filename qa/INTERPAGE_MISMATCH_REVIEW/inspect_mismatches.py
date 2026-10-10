"""Independent, read-only cross-page reconciliation from two uploaded CSVs.

Usage: python inspect_mismatches.py --merged PATH --p3 PATH --output DIRECTORY
Differences are always Page 3 minus the named reference, in Mm3.
No observations are repaired or shifted in the delivered source data.
"""
from pathlib import Path
import argparse
import json
import hashlib
import numpy as np
import pandas as pd

FIELDS = {
    'stock': ('source_p1_stock_today_mm3', 'p2_source_storage_current_total_corresponding_p2_mm3', 'p3_t1_stock_current_season_today_mm3', None),
    'inflow': ('source_p1_apport_today', 'p2_source_inflow_reporting_interval_p2_mm3', 'p3_t3_inflow_total_today_mm3', 'p3_t3_inflow_region_today_mm3'),
    'withdrawal': ('source_p1_release_yesterday', 'p2_source_outflow_reporting_interval_p2_mm3', 'p3_t4_withdrawal_total_today_mm3', 'p3_t4_withdrawal_region_today_mm3'),
}
REGIONS = {'nord':'REG-NORTH', 'centre':'REG-CENTRE', 'cap_bon':'REG-CAP-BON'}

def summary(g):
    e = g[g.evaluated]
    return pd.Series(dict(rows=len(g), evaluated=len(e), exact=int(e.exact.sum()),
        rounding_only=int((e.rounding_compatible & ~e.exact).sum()),
        exceeds_bound=int((~e.rounding_compatible).sum()),
        first=e.date.min(), last=e.date.max(),
        mean_difference=e.difference.mean(), median_difference=e.difference.median(),
        median_abs_difference=e.difference.abs().median(), max_abs_difference=e.difference.abs().max()))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--merged', required=True)
    ap.add_argument('--p3', required=True)
    ap.add_argument('--output', required=True)
    a=ap.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(a.merged,low_memory=False,parse_dates=['date'])
    pc=['bulletin_date','canonical_field_id','region_id','dam_id','raw_text','parsed_value',
        'semantic_state','source_file','source_sha256','layout_family','schema_id','layout_slot',
        'source_consistency_status','validation_status','record_id','row_label_en','source_node_id',
        'destination_node_id','is_accounting_observation','recovery_method','family_id','dam_candidate']
    p=pd.read_csv(a.p3,usecols=pc,low_memory=False,parse_dates=['bulletin_date']).rename(columns={'bulletin_date':'date'})
    p['parsed_value']=pd.to_numeric(p.parsed_value,errors='coerce')
    assert not d.duplicated(['dam_id','date']).any()
    region_map=d.groupby('dam_id').p2_source_region.agg(lambda x: x.dropna().unique().tolist())
    assert region_map.map(len).eq(1).all()
    d['region']=d.dam_id.map(region_map.map(lambda x:REGIONS[x[0]]))
    roster=d.loc[d.p1_row_present.eq(1)].copy()
    records=[]; aggregates=[]
    for metric,(p1,p2,total,regional) in FIELDS.items():
        for scope,rd in [('NATIONAL',roster)]+[(r,g) for r,g in roster.groupby('region')]:
            if scope!='NATIONAL' and regional is None: continue
            s=p[p.canonical_field_id.eq(total if scope=='NATIONAL' else regional)].copy()
            if scope!='NATIONAL': s=s[s.region_id.eq(scope)]
            assert not s.date.duplicated().any(),(metric,scope)
            s=s.set_index('date')[['parsed_value','raw_text','source_file','source_sha256','schema_id','layout_family','source_consistency_status','recovery_method']]
            s=s.rename(columns={'parsed_value':'p3_value','raw_text':'p3_raw','source_file':'p3_source_file','source_sha256':'p3_sha256'})
            n=rd.groupby('date').size().rename('expected_dams')
            for source,col in [('P1_DAM_SUM',p1),('P2_DAM_SUM',p2)]:
                agg=rd.groupby('date')[col].agg(['sum','count']).rename(columns={'sum':'available_sum','count':'available_dams'}).join(n)
                agg['reference']=agg.available_sum.where(agg.available_dams.eq(agg.expected_dams))
                agg['missing_dams']=rd[rd[col].isna()].groupby('date').dam_id.agg('|'.join)
                agg['missing_dams']=agg.missing_dams.fillna('')
                x=s.join(agg,how='left').reset_index()
                x['metric']=metric; x['scope']=scope; x['reference_source']=source
                x['difference']=x.p3_value-x.reference
                x['evaluated']=x.p3_value.notna() & x.reference.notna()
                x['exact']=x.evaluated & x.difference.abs().le(1e-8)
                # Explicit rounding sensitivity, not proof of common quantity.
                # National inflow is generally rounded to hundredths then padded
                # to three decimals. National withdrawal changes precision on
                # 2024-01-09. These are explicit sensitivity assumptions, not a
                # decimal-place parser or a statement that every source rounded.
                q=np.full(len(x), .001)
                if scope=='NATIONAL' and metric=='inflow': q[:]=.01
                if scope=='NATIONAL' and metric=='withdrawal': q[x.date.lt('2024-01-09')]=.01
                x['p3_rounding_quantum_assumed']=q
                x['rounding_bound_assumed']=q/2+x.expected_dams*.0005
                x['rounding_compatible']=x.evaluated & x.difference.abs().le(x.rounding_bound_assumed+1e-8)
                x['regime']=np.where(x.date.lt('2024-01-09'),'BEFORE_2024_01_09','FROM_2024_01_09')
                x['year']=x.date.dt.year; x['month']=x.date.dt.to_period('M').astype(str)
                records.append(x)
                ag=agg.reset_index();ag['metric']=metric;ag['scope']=scope;ag['source']=source
                aggregates.append(ag)
    c=pd.concat(records,ignore_index=True)
    c.to_csv(out/'comparisons_reconstructed.csv.gz',index=False)
    pd.concat(aggregates,ignore_index=True).to_csv(out/'source_aggregates.csv.gz',index=False)
    keys=['metric','scope','reference_source']
    for label,extra in [('summary',[]),('by_regime',['regime']),('by_year',['year']),('by_month',['month'])]:
        r=c.groupby(keys+extra).apply(summary,include_groups=False).reset_index()
        r.to_csv(out/f'comparison_{label}.csv',index=False)
        if label=='summary': print(r.to_string(index=False),flush=True)
    # Print source values around the two suspected changes, with every contributor.
    dates=d.date.between('2015-09-28','2015-10-10') | d.date.between('2024-01-04','2024-01-16')
    d.loc[dates].to_csv(out/'dam_rows_suspected_periods.csv',index=False)
    dates=p.date.between('2015-09-28','2015-10-10') | p.date.between('2024-01-04','2024-01-16')
    p.loc[dates].to_csv(out/'p3_cells_suspected_periods.csv',index=False)
    p[p.date.between('2022-06-30','2022-07-05') & p.canonical_field_id.eq('p3_t2_dam_stock_mm3')].to_csv(out/'july_2022_p3_dam_stock_cells.csv',index=False)
    # Retain small source subsets so the next stages do not reread the large exports.
    p[p.family_id.ne('T2')].to_csv(out/'p3_summary_transfer_cells.csv.gz',index=False)
    d.to_csv(out/'dam_sources.csv.gz',index=False)
    metadata=dict(merged_rows=len(d),p3_cells=len(p),p1_roster_rows=len(roster),
                  p1_dates=roster.date.nunique(),p3_dates=p.date.nunique(),
                  original_comparison_run_available=False,
                  rounding_note='Assumed precision bounds; these do not establish semantic equality.',
                  source_files={str(Path(f).resolve()):hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in [a.merged,a.p3]})
    (out/'SOURCE_RECEIPT.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2),flush=True)

if __name__=='__main__': main()
