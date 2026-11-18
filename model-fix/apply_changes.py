from pathlib import Path
import difflib
root=Path(r'F:\post_doc\guess_model\european_applications')
out=Path('model-fix'); originals={}
for name in ['cfxinput.cpp','cfxinput.h','globalco2file.h']:
 p=root/'modules'/name; originals[name]=p.read_text(); (out/'original'/name).parent.mkdir(parents=True,exist_ok=True); (out/'original'/name).write_text(originals[name])
s=originals['cfxinput.cpp']
s=s.replace(',spinup_climate_nyears(NYEAR_SPINUP_DATA)', ',climate_recycle_from_year(-1)\n\t,fixed_co2(0)\n\t,fixed_co2_year(1901)\n\t,fixed_co2_from_year(-1)\n\t,spinup_climate_nyears(NYEAR_SPINUP_DATA)')
anchor='\t// NOTE: GCP only wants'
pos=s.index(anchor)
s=s[:pos]+'''\tdeclare_parameter("climate_recycle_from_year", &climate_recycle_from_year, -1, 10000, "First year using reference climate; -1 means extend_climate_startyear + 1");
\tdeclare_parameter("fixed_co2", &fixed_co2, 0, 1, "Use reference-year CO2 from fixed_co2_from_year onward (default off)");
\tdeclare_parameter("fixed_co2_year", &fixed_co2_year, 0, 10000, "Reference year for fixed CO2");
\tdeclare_parameter("fixed_co2_from_year", &fixed_co2_from_year, -1, 10000, "First year using fixed CO2; -1 means fixed_co2_year + 1");

'''+s[pos:]
anchor='\tco2.load_file(param["file_co2"].str);'
s=s.replace(anchor,anchor+'''
\tif (climate_recycle_from_year < 0)
\t\tclimate_recycle_from_year = extend_climate_startyear + 1;
\tif (fixed_co2_from_year < 0)
\t\tfixed_co2_from_year = fixed_co2_year + 1;
\tif (extend_climate && fixed_spinup_climate)
\t\tfail("Choose either fixed_spinup_climate or extend_climate, not both");
\tif (fixed_co2 && !co2.contains_year(fixed_co2_year))
\t\tfail("Fixed CO2 reference year %d is absent from file_co2", fixed_co2_year);
''')
start=s.index('\t\t// need to synchronize the extended climate to the restart year')
end=s.index('\n\t}\n',start)
s=s[:start]+s[end:]
s=s.replace('calendar_year > extend_climate_startyear','calendar_year >= climate_recycle_from_year')
anchor='void CFXInput::populate_daily_arrays(Gridcell& gridcell) {'
variables=['temp','prec','insol','wetdays','min_temp','max_temp','pres','specifichum','relhum','wind']
addition='''
\t// Reconstruct the cycle phase from the calendar, including after restart.
\t// Set it BEFORE any daily/monthly variable is read.
\tif (extend_climate && date.get_calendar_year() >= climate_recycle_from_year) {
\t\tconst int index = (date.get_calendar_year() - climate_recycle_from_year) % extend_climate_nyears;
'''
for v in variables:
 addition+='\t\t'+('' if v in variables[:3] else 'if (cf_'+v+') ')+'extclim_'+v+'.set_year_index(index);\n'
addition+='\t}\n'
s=s.replace(anchor,anchor+addition)
start=s.index('\tGuessNC::CF::DateTime last_date = cf_temp->get_date_time',s.index(anchor))
end=s.index('\t// Get monthly ndep values',start)
s=s[:start]+'''\t// No cycle advancement here: each year's phase is selected above.

'''+s[end:]
s=s.replace('climate.co2 = co2[date.get_calendar_year()];','''const int simulation_year = date.get_calendar_year();
\tconst int co2_year = fixed_co2 && simulation_year >= fixed_co2_from_year
\t\t? fixed_co2_year : simulation_year;
\tclimate.co2 = co2[co2_year];''')
# guard unsupported calendar before indexing the fixed 365-day arrays
s=s.replace('int calendar_year = date.get_calendar_year();\n\n\tif (is_daily', '''int calendar_year = date.get_calendar_year();
\tif (extend_climate && calendar_year >= climate_recycle_from_year && date.year_length() != 365)
\t\tfail("Reference climate currently requires a 365-day model calendar");

\tif (is_daily''')
start=s.index('\tXGenericSpinupData::RawData source;',s.index('void CFXInput::load_extclim_data'))
end=s.index('\n}\n',start)
s=s[:start]+'''\tXGenericSpinupData::RawData source;
\textclim_data.years.clear();
\tconst int count = cf_var->get_timesteps();
\tconst bool daily = is_daily(cf_var);
\tconst int first_year = extend_climate_startyear - extend_climate_nyears + 1;
\tint timestep = 0;
\t// Bounded forward search also permits the first year in the file.
\twhile (timestep < count && cf_var->get_date_time(timestep).get_year() < first_year)
\t\t++timestep;
\tconst int days_in_month[] = {31,28,31,30,31,30,31,31,30,31,30,31};
\tfor (int year = first_year; year <= extend_climate_startyear; ++year) {
\t\tstd::vector<double> values;
\t\tfor (int month = 1; month <= 12; ++month) {
\t\t\tconst int days = daily ? days_in_month[month-1] : 1;
\t\t\tfor (int day = 1; day <= days; ++day) {
\t\t\t\tif (timestep >= count)
\t\t\t\t\tfail("Reference climate period %d..%d is incomplete", first_year, extend_climate_startyear);
\t\t\t\tDateTime dt = cf_var->get_date_time(timestep);
\t\t\t\tif (dt.get_year() != year || dt.get_month() != month || (daily && dt.get_day() != day))
\t\t\t\t\tfail("Missing or nonconsecutive reference climate date: expected %d-%02d-%02d", year, month, day);
\t\t\t\tvalues.push_back(cf_var->get_value(timestep++));
\t\t\t}
\t\t\t// Gregorian source leap days are omitted in the 365-day model cycle.
\t\t\tif (daily && month == 2 && timestep < count) {
\t\t\t\tDateTime dt = cf_var->get_date_time(timestep);
\t\t\t\tif (dt.get_year() == year && dt.get_month() == 2 && dt.get_day() == 29)
\t\t\t\t\t++timestep;
\t\t\t}
\t\t}
\t\tsource.push_back(values);
\t\textclim_data.years.push_back(year);
\t}
\textclim_data.get_data_from(source);'''+s[end:]
# one-year detrending has no trend to estimate
s=s.replace('void XGenericSpinupData::detrend_data(bool future) {','void XGenericSpinupData::detrend_data(bool future) {\n\tif (nbr_years() < 2) return;')
s=s.replace('void XGenericSpinupData::firstyear() {', '''void XGenericSpinupData::set_year_index(int index) {
\tif (index < 0 || index >= int(nbr_years()))
\t\tfail("Invalid reference climate year index %d", index);
\tthisyear = index;
}

void XGenericSpinupData::firstyear() {''')
h=originals['cfxinput.h'].replace('void firstyear();','void firstyear();\n\t\tvoid set_year_index(int index);')
h=h.replace('int extend_climate_startyear;','int extend_climate_startyear;\n\tint climate_recycle_from_year;\n\tint fixed_co2;\n\tint fixed_co2_year;\n\tint fixed_co2_from_year;')
c=originals['globalco2file.h'].replace('double operator[](int year) const;', '''double operator[](int year) const;

     /// Unlike operator[], this does not clamp an unavailable reference year.
     bool contains_year(int year) const {
         return !co2.empty() && year >= first_year &&
             year - first_year < static_cast<int>(co2.size());
     }''')
patch=[]
for name,text in [('cfxinput.cpp',s),('cfxinput.h',h),('globalco2file.h',c)]:
 patch.extend(difflib.unified_diff(originals[name].splitlines(True),text.splitlines(True),fromfile='a/modules/'+name,tofile='b/modules/'+name))
 (root/'modules'/name).write_text(text)
 (out/'modified'/name).parent.mkdir(parents=True,exist_ok=True)
 (out/'modified'/name).write_text(text)
(out/'reference-forcing.patch').write_text(''.join(patch))
print('Updated 3 model source files; originals and patch saved in model-fix')
