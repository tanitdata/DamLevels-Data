from __future__ import annotations

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def build_investigation(source: pd.DataFrame, p1: pd.DataFrame, p2: pd.DataFrame, merged: pd.DataFrame,
                        page1_root: str | Path, page2_root: str | Path, table_root: str | Path, figure_root: str | Path) -> dict:
    table_root=Path(table_root); figure_root=Path(figure_root); table_root.mkdir(parents=True,exist_ok=True); figure_root.mkdir(parents=True,exist_ok=True)
    source=source.copy()
    source_dates=[]
    for page,root in (("page1",page1_root),("page2",page2_root)):
        sm=pd.read_csv(Path(root)/"source_manifest.csv",low_memory=False)
        filename="source_filename" if "source_filename" in sm else "source_pdf"
        date="bulletin_date_parsed" if "bulletin_date_parsed" in sm else "bulletin_date"
        source_dates.append(pd.DataFrame({"page":page,"source_file":sm[filename],"bulletin_date":sm[date]}))
    source=source.merge(pd.concat(source_dates,ignore_index=True),on=["page","source_file"],how="left",validate="one_to_one")
    source["year"]=pd.to_datetime(source["bulletin_date"],errors="coerce").dt.year
    tables={
      "SOURCE_COVERAGE_BY_YEAR": source.groupby(["page","year"],dropna=False).size().rename("source_count").reset_index(),
      "SOURCE_COVERAGE_BY_PAGE": source.groupby("page").size().rename("source_count").reset_index(),
      "OBSERVATION_COVERAGE_BY_DAM": merged.groupby("canonical_dam_id").agg(observation_count=("bulletin_date","size"),first_date=("bulletin_date","min"),last_date=("bulletin_date","max")).reset_index(),
      "PAGE_PRESENCE_BY_DATE": merged.groupby(["bulletin_date","page_presence"]).size().rename("rows").reset_index(),
      "PAGE_PRESENCE_BY_DAM": merged.groupby(["canonical_dam_id","page_presence"]).size().rename("rows").reset_index(),
      "MISSINGNESS_BY_FIELD": pd.DataFrame({"field":merged.columns,"missing_count":merged.isna().sum().values,"missing_fraction":merged.isna().mean().values}),
      "MISSINGNESS_BY_DAM": merged.groupby("canonical_dam_id").apply(lambda x:x.isna().sum().sum(),include_groups=False).rename("missing_cells").reset_index(),
    }
    def read(root,name):
        path=Path(root)/name; return pd.read_csv(path,low_memory=False) if path.exists() else pd.DataFrame()
    lineages=[]; checks=[]; failures=[]; unresolved=[]
    for page,root in (("page1",page1_root),("page2",page2_root)):
        for bucket,name in ((lineages,"value_lineage.csv.gz"),(checks,"checksum_validation.csv.gz"),(failures,"extraction_failures.csv"),(unresolved,"unresolved_values.csv")):
            df=read(root,name); df["page"]=page; bucket.append(df)
    lin=pd.concat(lineages,ignore_index=True); chk=pd.concat(checks,ignore_index=True); fail=pd.concat(failures,ignore_index=True); unr=pd.concat(unresolved,ignore_index=True)
    status_parts=[]; field_parts=[]
    p1lin=lineages[0]; p2lin=lineages[1]
    if len(p1lin):
        status_parts.append(p1lin.assign(lineage_status=p1lin["parser_state"],page="page1")[["page","lineage_status"]])
        field_parts.append(p1lin.assign(canonical_field=p1lin["canonical_semantic_field"],page="page1")[["page","canonical_field"]])
    if len(p2lin):
        status_parts.append(p2lin.assign(lineage_status=p2lin["parse_status"],page="page2")[["page","lineage_status"]])
        field_parts.append(p2lin.assign(canonical_field=p2lin["canonical_semantic"],page="page2")[["page","canonical_field"]])
    status_frame=pd.concat(status_parts,ignore_index=True); field_frame=pd.concat(field_parts,ignore_index=True)
    tables["LINEAGE_STATUS_SUMMARY"]=status_frame.groupby(["page","lineage_status"],dropna=False).size().rename("rows").reset_index()
    tables["LINEAGE_BY_FIELD"]=field_frame.groupby(["page","canonical_field"],dropna=False).size().rename("rows").reset_index()
    tables["CHECKSUM_DISPOSITION_SUMMARY"]=chk.groupby(["page","disposition"],dropna=False).size().rename("rows").reset_index() if "disposition" in chk else pd.DataFrame(columns=["page","disposition","rows"])
    tables["FAILURE_SUMMARY"]=fail.groupby(["page","failure_class"],dropna=False).size().rename("rows").reset_index() if "failure_class" in fail else pd.DataFrame(columns=["page","failure_class","rows"])
    page2_unr=unr[unr["page"].eq("page2")].copy()
    rs=page2_unr[page2_unr["canonical_semantic"].eq("p2_rs_unresolved_prohibited")]
    expressions=page2_unr[page2_unr["disposition"].eq("SOURCE_EXPRESSION_PRESERVED_NO_INFERENCE")]
    page2_summary=pd.read_csv(Path(page2_root)/"run_summary.csv").iloc[0]
    tables["QUALITY_STATUS_SUMMARY"]=pd.DataFrame([
        {"status_group":"actionable","status_category":"Page-2 extraction failures","rows":int(page2_summary["failure_count"]),"actionable":True,"parent_category":"","interpretation":"Extraction failures requiring action"},
        {"status_group":"actionable","status_category":"Page-2 actionable parser ambiguities","rows":int(page2_summary["ambiguous_row_count"]),"actionable":True,"parent_category":"","interpretation":"Ambiguous detected rows requiring parser review"},
        {"status_group":"protected_source_state","status_category":"Page-2 protected R.S. states","rows":int(len(rs)),"actionable":False,"parent_category":"","interpretation":"Governed R.S. values deliberately protected from scientific interpretation"},
        {"status_group":"protected_source_state","status_category":"Numeric parsed but deliberately uninterpreted","rows":int(rs["parse_status"].eq("NUMERIC_PARSED_RS_UNRESOLVED_PROHIBITED").sum()),"actionable":False,"parent_category":"Page-2 protected R.S. states","interpretation":"Numeric source text preserved without assigning R.S. semantics"},
        {"status_group":"protected_source_state","status_category":"Source blanks preserved as missing","rows":int(rs["parse_status"].eq("SOURCE_BLANK").sum()),"actionable":False,"parent_category":"Page-2 protected R.S. states","interpretation":"Blank R.S. source cells preserved as missing"},
        {"status_group":"preserved_expression","status_category":"Page-2 preserved nonnumeric source expressions","rows":int(len(expressions)),"actionable":False,"parent_category":"","interpretation":"Nonnumeric source expressions preserved verbatim without inference"},
    ])
    pairs=[("storage","page1__p1_stock_today_mm3","page2__storage_current_total_corresponding_p2_mm3"),("inflow","page1__p1_apport_today","page2__inflow_reporting_interval_p2_mm3"),("outflow","page1__p1_release_yesterday","page2__outflow_reporting_interval_p2_mm3")]
    comparisons=[]
    for label,a,b in pairs:
        if a in merged and b in merged:
            d=pd.DataFrame({"pair":label,"bulletin_date":merged.bulletin_date,"canonical_dam_id":merged.canonical_dam_id,"page1":pd.to_numeric(merged[a],errors="coerce"),"page2":pd.to_numeric(merged[b],errors="coerce")}).dropna(subset=["page1","page2"]); d["difference"]=d.page1-d.page2; comparisons.append(d)
    comp=pd.concat(comparisons,ignore_index=True) if comparisons else pd.DataFrame(columns=["pair","bulletin_date","canonical_dam_id","page1","page2","difference"])
    tables["CROSS_PAGE_COMPARISON_SUMMARY"]=comp.groupby("pair").difference.agg(["count","mean","median","min","max"]).reset_index() if len(comp) else pd.DataFrame(columns=["pair","count","mean","median","min","max"])
    tables["LARGEST_CROSS_PAGE_DIFFERENCES"]=comp.assign(abs_difference=comp.difference.abs()).sort_values("abs_difference",ascending=False).head(1000)
    for name,df in tables.items(): df.to_csv(table_root/f"{name}.csv",index=False)
    # Twelve deterministic, labelled figures; empty states remain explicit evidence.
    specs=[("01_source_coverage_over_time",tables["SOURCE_COVERAGE_BY_YEAR"],"year","source_count","Source coverage over time","PDF sources"),("02_observations_by_dam",tables["OBSERVATION_COVERAGE_BY_DAM"].nlargest(20,"observation_count"),"canonical_dam_id","observation_count","Observations by dam","observations"),("03_page_presence_over_time",tables["PAGE_PRESENCE_BY_DATE"],"bulletin_date","rows","Page presence over time","rows"),("04_missingness_by_field",tables["MISSINGNESS_BY_FIELD"].nlargest(20,"missing_fraction"),"field","missing_fraction","Missingness by field","fraction missing"),("05_missingness_heatmap_by_dam",tables["MISSINGNESS_BY_DAM"].nlargest(20,"missing_cells"),"canonical_dam_id","missing_cells","Missingness by dam","missing cells"),("06_lineage_status_distribution",tables["LINEAGE_STATUS_SUMMARY"],"lineage_status","rows","Lineage status distribution","lineage cells"),("07_checksum_dispositions",tables["CHECKSUM_DISPOSITION_SUMMARY"],"disposition","rows","Checksum dispositions","rows"),("08_quality_status",tables["QUALITY_STATUS_SUMMARY"],"status_category","rows","Page-2 quality status: actionable failures vs protected source states","preserved-state rows")]
    for label,a,b in pairs:
        specs.append((f"{len(specs)+1:02d}_{label}_page1_vs_page2",comp[comp.pair==label],"page1","page2",f"{label.title()}: Page 1 vs Page 2","Page 2 (reported units)"))
    specs.append(("12_cross_page_difference_over_time",comp,"bulletin_date","difference","Cross-page difference over time","Page 1 minus Page 2 (reported units)"))
    for fname,df,x,y,title,ylabel in specs:
        fig,ax=plt.subplots(figsize=(10,5)); clean=df.dropna(subset=[x,y]) if x in df and y in df else pd.DataFrame()
        if len(clean):
            if fname == "08_quality_status":
                colors=clean["actionable"].map({True:"#c0392b",False:"#2e86c1"})
                ax.barh(clean[x],clean[y],color=colors)
                ax.invert_yaxis()
                for index,value in enumerate(clean[y]): ax.text(value,index,f" {int(value):,}",va="center")
            elif pd.api.types.is_numeric_dtype(clean[x]): ax.scatter(clean[x],clean[y],s=5,alpha=.3)
            else: clean.groupby(x)[y].sum().plot(kind="bar",ax=ax)
        else: ax.text(.5,.5,"No comparable observations",ha="center",va="center",transform=ax.transAxes)
        if fname == "08_quality_status":
            ax.set_title(f"{title}\n145,695 is a reporting union, not failed observations")
            ax.set_xlabel(ylabel); ax.set_ylabel("Governed quality category")
        else:
            ax.set_title(f"{title} (n={len(clean):,}; missing excluded)"); ax.set_xlabel(x.replace("_"," ")); ax.set_ylabel(ylabel)
        fig.tight_layout(); fig.savefig(figure_root/f"{fname}.png",dpi=150); plt.close(fig)
    return {"table_count":len(tables),"figure_count":len(specs)}
