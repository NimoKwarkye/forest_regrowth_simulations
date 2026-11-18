"""Generate focused C++ tests using function bodies read from the actual model source.
NetCDF/model framework are minimal test doubles; this is not a full model build.
"""
from pathlib import Path
import re
root=Path(r'F:\post_doc\guess_model\european_applications')
s=(root/'modules/cfxinput.cpp').read_text()
def function(signature):
 start=s.index(signature); brace=s.index('{',start); depth=1; end=brace+1
 while depth:
  depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]
h=(root/'modules/cfxinput.h').read_text(); start=h.index('class XGenericSpinupData');end=h.index('\n\t};',start)+5
cls=h[start:end]
parts=[r'''
#include <vector>
#include <string>
#include <stdexcept>
#include <iostream>
#include <cstdio>
#include <limits>
#include <cstdarg>
#include <cassert>
using std::size_t;
void fail(const char* message, ...) { throw std::runtime_error(message); }
struct Clock { int year=1901; int day=0; int get_calendar_year() const {return year;} } date;
void dprintf(const char*, ...) {}
bool readfor(FILE* f, const char*, int* y, double* c) {return fscanf(f,"%d %lf",y,c)==2;}
struct DateTime {
 int y,m,d;
 int get_year() const{return y;} int get_month() const{return m;} int get_day() const{return d;}
};
namespace GuessNC { namespace CF {
struct GridcellOrderedVariable {
 std::vector<DateTime> dates; std::vector<double> values; bool daily=true;
 int get_timesteps()const{return int(dates.size());}
 DateTime get_date_time(int i)const{return dates.at(i);}
 double get_value(int i)const{return values.at(i);}
};
}}
using GuessNC::CF::GridcellOrderedVariable;
bool is_daily(const GridcellOrderedVariable* v){return v->daily;}
''',cls]
for sig in ['XGenericSpinupData::XGenericSpinupData()', 'void XGenericSpinupData::get_data_from', 'double XGenericSpinupData::operator[]', 'void XGenericSpinupData::nextyear', 'void XGenericSpinupData::set_year_index', 'void XGenericSpinupData::firstyear', 'size_t XGenericSpinupData::nbr_years']:
 parts.append(function(sig))
parts.append((root/'modules/globalco2file.h').read_text())
co2=(root/'modules/globalco2file.cpp').read_text()
parts.append(re.sub(r'^#include.*$', '', co2,flags=re.M))
variables=['temp','prec','insol','wetdays','min_temp','max_temp','pres','specifichum','relhum','wind']
parts.append('struct Gridcell {};\nclass CFXInput { public:\nint extend_climate_startyear=1901, extend_climate_nyears=1, extend_climate=1, climate_recycle_from_year=1902;\nint fixed_co2=0, fixed_co2_year=1901, fixed_co2_from_year=1905;\nGlobalCO2File co2;\n')
for v in variables:
 parts.append('XGenericSpinupData extclim_'+v+'; GridcellOrderedVariable* cf_'+v+'=nullptr;')
parts.append('void load_extclim_data(const GridcellOrderedVariable*, XGenericSpinupData&);\nvoid populate_daily_arrays(Gridcell&);\ndouble co2_value() {\n')
a=s.index('\tconst int simulation_year =',s.index('bool CFXInput::getclimate'))
b=s.index('\n\tif (date.day',a)
parts.append(s[a:b].replace('climate.co2 = co2[co2_year];','return co2[co2_year];'))
parts.append('}\n};')
parts.append(function('void CFXInput::load_extclim_data'))
a=s.index('void CFXInput::populate_daily_arrays');b=s.index('\t// Extract daily values',a)
parts.append(s[a:b]+'}\n')
parts.append(r'''
GridcellOrderedVariable weather(int first,int last,bool daily=true,bool leap=false) {
 GridcellOrderedVariable v;v.daily=daily;
 int lengths[]={31,28,31,30,31,30,31,31,30,31,30,31};
 for(int y=first;y<=last;++y)for(int m=1;m<=12;++m) {
  int n=daily?lengths[m-1]:1;
  if(daily && leap && m==2 && y%4==0)++n;
  for(int d=1;d<=n;++d){v.dates.push_back({y,m,d});v.values.push_back(y*10000+m*100+d);}
 }
 return v;
}
template<class F> void rejects(F f) {bool caught=false;try{f();}catch(const std::exception&){caught=true;}assert(caught);}
int main(){
 int checks=0;
 CFXInput m; auto v=weather(1901,1904); XGenericSpinupData data;
 m.load_extclim_data(&v,data);assert(data[0]==19010101 && data[364]==19011231);++checks;
 // Exact one-year file and repeat loading (metadata must not accumulate).
 auto one=weather(1901,1901);m.load_extclim_data(&one,data);m.load_extclim_data(&one,data);assert(data.years.size()==1);++checks;
 auto empty=weather(1902,1901);rejects([&]{m.load_extclim_data(&empty,data);});++checks;
 auto absent=weather(1902,1903);rejects([&]{m.load_extclim_data(&absent,data);});++checks;
 auto incomplete=one;incomplete.dates.pop_back();incomplete.values.pop_back();rejects([&]{m.load_extclim_data(&incomplete,data);});++checks;
 auto missing=one;missing.dates.erase(missing.dates.begin()+40);missing.values.erase(missing.values.begin()+40);rejects([&]{m.load_extclim_data(&missing,data);});++checks;
 auto duplicate=one;duplicate.dates[40]=duplicate.dates[39];rejects([&]{m.load_extclim_data(&duplicate,data);});++checks;
 auto monthly=weather(1901,1901,false);m.load_extclim_data(&monthly,data);assert(data[11]==19011201);++checks;
 auto leap=weather(1904,1904,true,true);m.extend_climate_startyear=1904;m.load_extclim_data(&leap,data);assert(data[59]==19040301 && data[364]==19041231);++checks;
 m.extend_climate_startyear=1901;m.extend_climate_nyears=1;
 m.load_extclim_data(&one,m.extclim_temp);m.extclim_prec=m.extclim_insol=m.extclim_temp;
 Gridcell cell;
 m.cf_wind=&one;m.extclim_wind=m.extclim_temp;
 m.cf_relhum=&one;m.extclim_relhum=m.extclim_temp;
 for(int y=1902;y<2200;++y){date.year=y;m.populate_daily_arrays(cell);assert(m.extclim_temp[0]==19010101 && m.extclim_wind[364]==19011231 && m.extclim_relhum[0]==19010101);}++checks;
 // Independent object at arbitrary restart year gives same multiyear phase.
 m.extend_climate_startyear=1903;m.extend_climate_nyears=3;m.climate_recycle_from_year=1904;
 m.load_extclim_data(&v,m.extclim_temp);m.extclim_prec=m.extclim_insol=m.extclim_temp;m.extclim_wind=m.extclim_relhum=m.extclim_temp;
 for(int y=1904;y<1930;++y){date.year=y;m.populate_daily_arrays(cell);CFXInput resumed=m;resumed.extclim_temp.firstyear();resumed.populate_daily_arrays(cell);assert(resumed.extclim_temp[0]==m.extclim_temp[0]);assert(m.extclim_temp[0]==(1901+(y-1904)%3)*10000+101);}++checks;
 rejects([&]{m.extclim_temp.set_year_index(3);});++checks;
 // Actual GlobalCO2File reader with a simple readfor adapter.
 FILE* f=fopen("co2-fixture.txt","w");for(int y=1901;y<=1910;++y)fprintf(f,"%d %d\n",y,300+y-1901);fclose(f);
 m.co2.load_file("co2-fixture.txt");assert(m.co2.contains_year(1901)&&!m.co2.contains_year(1900)&&!m.co2.contains_year(1911));++checks;
 date.year=1906;assert(m.co2_value()==305);m.fixed_co2=1;assert(m.co2_value()==300);date.year=1904;assert(m.co2_value()==303);date.year=2100;assert(m.co2_value()==300);++checks;
 std::cout<<checks<<" focused C++ scenarios passed\n";
}
''')
Path('model-fix/forcing_tests.cpp').write_text('\n'.join(parts))
