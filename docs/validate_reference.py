"""Read and plot the supplied historical archive without treating it as a new run.

Usage: python -m docs.validate_reference --archive PATH --output PATH
"""
import argparse
import json
from pathlib import Path
from lpjregrowth.collect import read_table

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[row for _,row,_ in read_table(args.archive/'agb_gridcell.out.gz')]
    sites={(r['Lon'],r['Lat']) for r in rows}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5))
    trees=['BNE','BINE','BNS','TeNE','TeBS','IBS','TeBE','TrBE','TrIBE','TrBR','TrIBR']
    for site in sorted(sites):
        series=sorted([r for r in rows if (r['Lon'],r['Lat'])==site],key=lambda r:r['Year'])
        ax.plot([r['Year'] for r in series],[sum(r[p] for p in trees) for r in series],label=f'Woody PFTs: {site}')
        ax.plot([r['Year'] for r in series],[r['Total'] for r in series],linestyle=':',label='Total including grasses')
    for year in (1905,1965):
        ax.axvline(year,color='gray',linestyle='--',linewidth=1)
    ax.set(xlabel='Calendar year',ylabel='Model-reported aboveground carbon [kg C m$^{-2}$]',title='Existing reference archive: repeated cuts, not a new single-cut simulation')
    ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.tight_layout()
    for suffix in ('png','pdf'):fig.savefig(args.output/f'reference_aboveground.{suffix}',dpi=180)
    plt.close(fig)
    summary={'archive':str(args.archive),'records':len(rows),'sites':list(sites),
             'years':[min(r['Year'] for r in rows),max(r['Year'] for r in rows)],
             'woody_PFT_sum_in_cut_years':{str(y):[sum(r[p] for p in trees) for r in rows if r['Year']==y] for y in (1905,1965)},
             'limitation':'Existing archived output only. Does not establish executable provenance or validate new single-cut runs.'}
    (args.output/'reference_check.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
