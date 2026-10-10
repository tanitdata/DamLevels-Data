"""Investigate contributor coverage and changes, without altering source CSVs.
Run after inspect_mismatches.py: python temporal_checks.py --output DIRECTORY
"""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',required=True); a=ap.parse_args()
    out=Path(a.output)
    d=pd.read_csv(out/'dam_sources.csv.gz',low_memory=False,parse_dates=['date'])
    p=pd.read_csv(out/'p3_summary_transfer_cells.csv.gz',low_memory=False,parse_dates=['date'])
    c=pd.read_csv(out/'comparisons_reconstructed.csv.gz',low_memory=False,parse_dates=['date'])
    aggregates=pd.read_csv(out/'source_aggregates.csv.gz',low_memory=False,parse_dates=['date'])
    # The union catches rows present on just one page. It is not an independently
    # verified official dam roster and cannot catch an omission shared by both.
    miss=d[d.p1_row_present.ne(1)&d.p2_row_present.eq(1)].copy()
    miss.to_csv(out/'p2_rows_excluded_by_p1_roster.csv',index=False)
    stock='p2_source_storage_current_total_corresponding_p2_mm3'
    national=c[(c.metric=='stock')&(c.scope=='NATIONAL')&(c.reference_source=='P2_DAM_SUM')].set_index('date')
    u=d[d.p1_row_present.eq(1)|d.p2_row_present.eq(1)].groupby('date')[stock].agg(['size','count','sum'])
    u['p2_union_complete_sum']=u['sum'].where(u['size'].eq(u['count']))
    u=u.join(national[['p3_value','reference','difference','expected_dams']])
    u['union_difference']=u.p3_value-u.p2_union_complete_sum
    u['excluded_from_p1_roster_dams']=miss.groupby('date').dam_id.agg('|'.join)
    u['excluded_dams_p2_stock_sum']=miss.groupby('date')[stock].sum(min_count=1)
    u.reset_index().to_csv(out/'stock_roster_comparison.csv',index=False)
    large_old=u.difference.abs().gt((u.expected_dams+1)*.0005+1e-8)
    large_new=u.union_difference.abs().gt((u['size']+1)*.0005+1e-8)
    u[large_old|large_new].reset_index().to_csv(out/'stock_exception_dates.csv',index=False)
    oct=u.loc['2015-10-02':'2015-10-07'].copy()
    for dam in ['benmetir','sidiaich']:
        oct[dam+'_p2_stock']=d[d.dam_id.eq(dam)].set_index('date')[stock]
    oct.reset_index().to_csv(out/'october_2015_explanation.csv',index=False)
    # Whole-panel staleness is evidence for review, not proof that P3 is correct.
    july=pd.DataFrame(index=pd.date_range('2022-06-30','2022-07-05',name='date'))
    for page,col in [('p1','source_p1_stock_today_mm3'),('p2',stock)]:
        mat=d.pivot(index='date',columns='dam_id',values=col).sort_index()
        previous=mat.reindex(mat.index-pd.Timedelta(days=1));previous.index=mat.index
        july[page+'_stock_sum']=mat.sum(axis=1,min_count=36)
        july[page+'_unchanged_dams']=(mat.notna()&previous.notna()&(mat-previous).abs().le(1e-8)).sum(axis=1)
    july['p3_national_stock']=p[p.canonical_field_id.eq('p3_t1_stock_current_season_today_mm3')].set_index('date').parsed_value
    july.reset_index().to_csv(out/'july_2022_flat_then_jump.csv',index=False)
    jc=pd.read_csv(out/'july_2022_p3_dam_stock_cells.csv')
    # The first stage uses date; an older intermediate used bulletin_date.
    if 'bulletin_date' in jc: jc=jc.rename(columns={'bulletin_date':'date'})
    jc['date']=pd.to_datetime(jc.date)
    examples=[]
    for dam,p3id in [('sidisalem','DAM-SIDI-SALEM'),('joumine','DAM-JOUMINE')]:
        zz=d[d.dam_id.eq(dam)&d.date.between('2022-07-01','2022-07-04')][['date','dam_id','source_p1_stock_today_mm3',stock,'source_source_filename','p2_source_source_file']].copy()
        pp=jc[jc.dam_id.eq(p3id)][['date','parsed_value','source_file']].rename(columns={'parsed_value':'p3_dam_stock','source_file':'p3_source_file'})
        examples.append(zz.merge(pp,on='date',how='left',validate='one_to_one'))
    pd.concat(examples).to_csv(out/'july_2022_dam_examples.csv',index=False)
    # Exact calendar-date joins, not previous/next available rows. Every offset
    # is scored on the identical intersection for the given pair and regime.
    shifts=[]
    for (metric,scope,src),g in c.groupby(['metric','scope','reference_source']):
        g=g.set_index('date').sort_index()
        r=aggregates[(aggregates.metric==metric)&(aggregates.scope==scope)&(aggregates.source==src)].set_index('date').reference
        z=g[['p3_value','rounding_bound_assumed']].copy()
        for k in [-1,0,1]: z[f'ref_{k}']=r.reindex(z.index+pd.Timedelta(days=k)).to_numpy()
        # Same day-dependent precision bound for every candidate alignment.
        z=z.dropna()
        for regime,zz in [('ALL',z),('BEFORE_2024_01_09',z[z.index<'2024-01-09']),('FROM_2024_01_09',z[z.index>='2024-01-09'])]:
            for k in [-1,0,1]:
                e=zz.p3_value-zz[f'ref_{k}']
                shifts.append(dict(metric=metric,scope=scope,reference_source=src,regime=regime,
                    reference_date_offset_days=k,n=len(e),mae=e.abs().mean(),median_abs=e.abs().median(),
                    exact=int(e.abs().le(1e-8).sum()),within_bound=int(e.abs().le(zz.rounding_bound_assumed+1e-8).sum())))
    pd.DataFrame(shifts).to_csv(out/'calendar_shift_comparison.csv',index=False)
    # Internal Page-3 national versus regional sum, independent of P1/P2.
    intern=[]
    for metric,f1,f2 in [('inflow','p3_t3_inflow_total_today_mm3','p3_t3_inflow_region_today_mm3'),
                         ('withdrawal','p3_t4_withdrawal_total_today_mm3','p3_t4_withdrawal_region_today_mm3')]:
        nat=p[p.canonical_field_id.eq(f1)].set_index('date')
        reg=p[p.canonical_field_id.eq(f2)].pivot(index='date',columns='region_id',values='parsed_value')
        z=nat[['parsed_value','raw_text']].rename(columns={'parsed_value':'national','raw_text':'national_raw'})
        z['region_sum']=reg.sum(axis=1,min_count=3);z['difference']=z.national-z.region_sum
        z['metric']=metric;z['regime']=np.where(z.index<'2024-01-09','BEFORE_2024_01_09','FROM_2024_01_09')
        z['is_hundredth_grid']=np.isclose(z.national*100,np.round(z.national*100),atol=1e-7,rtol=0)
        intern.append(z.reset_index())
    pd.concat(intern).to_csv(out/'p3_internal_arithmetic.csv',index=False)
    # Changes in available observations and completeness by period.
    coverage=[]
    periods=[('before_2024_01_09','2014-07-02','2024-01-08'),
             ('2024_01_09_to_04_26','2024-01-09','2024-04-26'),
             ('from_2024_04_27','2024-04-27','2025-10-10')]
    for period,start,end in periods:
        for metric in ['stock','inflow','withdrawal']:
            g=c[(c.scope=='NATIONAL')&(c.metric==metric)&(c.reference_source=='P2_DAM_SUM')&c.date.between(start,end)]
            coverage.append(dict(period=period,metric=metric,p3_dates=len(g),evaluated=int(g.evaluated.sum()),
                first_evaluated=g.loc[g.evaluated,'date'].min(),last_evaluated=g.loc[g.evaluated,'date'].max()))
    pd.DataFrame(coverage).to_csv(out/'national_p2_coverage_periods.csv',index=False)
    # A descriptive single change-point in the frequency of large North
    # discrepancies. This is not an independently confirmatory significance test.
    w=c[(c.metric=='withdrawal')&(c.scope=='REG-NORTH')&(c.reference_source=='P1_DAM_SUM')&c.evaluated].sort_values('date')
    b=(~w.rounding_compatible).astype(int).to_numpy(); n=len(b); counts=np.cumsum(b)
    def ll(s,n):
        q=np.clip(s/n,1e-12,1-1e-12)
        return s*np.log(q)+(n-s)*np.log(1-q)
    scan=[]
    for k in range(180,n-180):
        scan.append(dict(split_index=k,first_date_after=w.iloc[k].date,
            log_likelihood=ll(counts[k-1],k)+ll(counts[-1]-counts[k-1],n-k),
            before_large_fraction=counts[k-1]/k,after_large_fraction=(counts[-1]-counts[k-1])/(n-k)))
    scan=pd.DataFrame(scan).sort_values('log_likelihood',ascending=False)
    scan.head(15).to_csv(out/'withdrawal_change_candidates.csv',index=False)
    # Test explicit physical-transfer explanations on matched dates. T5 row 4
    # remains an accounting observation and is deliberately not a physical sum.
    t=p[p.canonical_field_id.eq('p3_t5_transfer_day_mm3')].pivot(index='date',columns='row_label_en',values='parsed_value')
    names={
        'barbara_transfer':'from Barbara dam to Bouhertma dam (Oued Ghrib)',
        'barrak_transfer':'from Sidi El Barrak dam to Sejnane dam',
        'ziatine_transfer':'from Zayatin dam to Sejnane dam'}
    t=t.rename(columns={v:k for k,v in names.items()})[list(names)]
    t['all_three_transfers']=t.sum(axis=1,min_count=3)
    t['ichkeul']=p[p.canonical_field_id.eq('p3_t6_ichkeul_day_mm3')].set_index('date').parsed_value
    t['three_transfers_plus_ichkeul']=t.all_three_transfers+t.ichkeul
    z=w.set_index('date')[['p3_value','reference','difference','rounding_bound_assumed']].join(t)
    z['gross_minus_p3']=z.reference-z.p3_value
    z.reset_index().to_csv(out/'withdrawal_transfer_diagnostics.csv',index=False)
    rows=[]
    for period,start,end in periods[:1]+[('from_2024_01_09','2024-01-09','2025-10-10')]:
        for col in t.columns:
            zz=z.loc[start:end,['gross_minus_p3','rounding_bound_assumed',col]].dropna()
            e=zz.gross_minus_p3-zz[col]
            rows.append(dict(period=period,candidate=col,n=len(zz),uncorrected_mae=zz.gross_minus_p3.abs().mean(),
                after_subtraction_mae=e.abs().mean(),median_residual=e.median(),
                within_bound=int(e.abs().le(zz.rounding_bound_assumed+1e-8).sum())))
    pd.DataFrame(rows).to_csv(out/'transfer_hypothesis_summary.csv',index=False)
    # Source-backed multi-panel evidence figure, independent axes and dates.
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
    fig,axs=plt.subplots(4,1,figsize=(12,13),layout='constrained')
    s=c[(c.metric=='inflow')&(c.scope=='NATIONAL')&(c.reference_source=='P2_DAM_SUM')&c.evaluated].sort_values('date')
    axs[0].scatter(s.date,s.difference,s=10,color='#176b87')
    axs[0].axhline(0,color='grey',lw=.6);axs[0].set_ylabel('Difference (Mm³)')
    axs[0].set_title('National inflow: small rounding-scale differences; sparse earlier coverage',loc='left')
    axs[1].plot(oct.index,oct.difference,'o-',color='#bb4b35',label='P2 sum restricted to extracted P1 roster')
    axs[1].plot(oct.index,oct.union_difference,'o-',color='#176b87',label='P2 sum including Ben Metir and Sidi Aïch')
    axs[1].set_ylabel('Difference (Mm³)');axs[1].legend(fontsize=9,loc='center left')
    axs[1].set_title('October 2015 stock cluster: two excluded contributors explain the gap',loc='left')
    axs[2].scatter(w.date,w.difference,s=5,color='#176b87',alpha=.6)
    axs[2].axvline(pd.Timestamp('2024-01-09'),color='#bb4b35',ls='--',label='9 January 2024')
    axs[2].set_title('Northern withdrawal: discrepancy begins in January 2024',loc='left')
    axs[2].set_ylabel('Difference (Mm³)');axs[2].legend(loc='lower left')
    axs[3].plot(july.index,july.p1_stock_sum,'o-',color='#bb4b35',label='Page 1 / Page 2: identical sums')
    axs[3].plot(july.index,july.p3_national_stock,'o-',color='#176b87',label='Page 3 printed national stock')
    axs[3].set_title('July 2022: storage repeats on Pages 1 and 2, while Page 3 changes',loc='left')
    axs[3].set_ylabel('Storage (Mm³)');axs[3].legend(fontsize=9)
    for ax in axs:
        ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Differences = Page 3 minus the named sum\nSource values preserved; no global date shift or forced correction',fontsize=13)
    fig.savefig(out/'mismatch_timeline.png',dpi=160);plt.close(fig)
    cluster=oct.loc['2015-10-03':'2015-10-06']
    receipt=dict(october_restricted_max_abs=float(cluster.difference.abs().max()),
        october_union_max_abs=float(cluster.union_difference.abs().max()),
        july_2_and_3_p1_unchanged_dams={str(k.date()):int(v) for k,v in july.loc['2022-07-02':'2022-07-03','p1_unchanged_dams'].items()},
        highest_likelihood_descriptive_break=str(scan.iloc[0].first_date_after.date()),
        shift_definition='P3(t) versus reference(t+k), k in {-1,0,1}; identical complete dates per pair/regime',
        caveat='Union roster cannot detect contributors missing from both pages. No source values corrected.')
    (out/'TEMPORAL_CHECK_RECEIPT.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2),flush=True)
    print('OCTOBER',oct[['p3_value','reference','difference','benmetir_p2_stock','sidiaich_p2_stock','p2_union_complete_sum','union_difference']].to_string(),flush=True)
    print('SHIFTS',pd.DataFrame(shifts).query('scope == "NATIONAL" and reference_source == "P2_DAM_SUM"').to_string(index=False),flush=True)
    print('TRANSFER',pd.DataFrame(rows).to_string(index=False),flush=True)

if __name__=='__main__': main()
