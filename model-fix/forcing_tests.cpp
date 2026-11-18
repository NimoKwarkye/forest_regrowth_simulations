
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

class XGenericSpinupData {
	public:
		static const int DAYS_PER_YEAR = 365;
		
		/// Datatype for the data, a 2D matrix of doubles
		typedef std::vector<std::vector<double> > RawData;
		
		XGenericSpinupData();
		
		/// Loads the underlying forcing data (and sets the "current" year to 0)
		void get_data_from(RawData& source);
		
		/// Gets the value for a given timestep in the "current" year
		double operator[](int ts) const;
		
		/// Goes to the next year
		void nextyear();
		
		/// Goes to the first year
		void firstyear();
		void set_year_index(int index);
		
		/// Removes trend from the original data
		void detrend_data(bool future = false);
		
		/// Returns the number of years used to construct the spinup dataset
		size_t nbr_years() const;
		
		/// for debugging: the years that are used for the spinup rawdata
		std::vector<int> years;
		
		/// The "current" year
		int thisyear;
		
	private:
		/// The forcing data which is used over and over during the spinup
		RawData data;
	};

XGenericSpinupData::XGenericSpinupData()
: thisyear(0) {
}
void XGenericSpinupData::get_data_from(RawData& source) {
	data = source;
	
	if (source.empty()) {
		fail("No source data given to XGenericSpinupData::get_data_from()");
	}
	
	for (size_t i = 0; i < source.size(); ++i) {
		if ((source[i].size() != 12 &&
				 source[i].size() % DAYS_PER_YEAR != 0) ||
				source[i].empty()) {
			fail("Incorrect number of timesteps per year in data given to\n"\
					 "XGenericSpinupData (got %d)", source[i].size());
		}
		
		if (i > 0 && source[i].size() != source[i-1].size()) {
			fail("Different number of timesteps in different years in\n"\
					 "data given to XGenericSpinupData::get_data_from()");
		}
	}
	
	firstyear();
}
double XGenericSpinupData::operator[](int ts) const {
	if (ts < 0 || ts >= int(data[thisyear].size())) {
		fail("Trying to access data for timestep %d during spinup\n"\
				 "(should be 0-%d)", ts, data[thisyear].size());
	}
	return data[thisyear][ts];
}
void XGenericSpinupData::nextyear() {
	thisyear = (thisyear + 1) % nbr_years();
}
void XGenericSpinupData::set_year_index(int index) {
	if (index < 0 || index >= int(nbr_years()))
		fail("Invalid reference climate year index %d", index);
	thisyear = index;
}
void XGenericSpinupData::firstyear() {
	thisyear = 0;
}
size_t XGenericSpinupData::nbr_years() const {
	return data.size();
}
///////////////////////////////////////////////////////////////////////////////////////
/// \file globalco2file.h
/// \brief A class for reading in CO2 values from a text file
///
///
/// \author Joe Siltberg
///
/// $Date: 2013-10-10 10:20:33 +0200 (Thu, 10 Oct 2013) $
///
///////////////////////////////////////////////////////////////////////////////////////

#ifndef LPJ_GUESS_GLOBALCO2FILE_H
#define LPJ_GUESS_GLOBALCO2FILE_H

#include <vector>

/// Reads in and stores CO2 values from a text file
class GlobalCO2File {
public:
	 GlobalCO2File();

	 /// Loads CO2 values from text file
	 /** The text file specifies CO2 values for historical period, each line in
	  *  the format <year> <co2-value>. The years can be for any period but all
	  *  years in the period must be specified.
	  */
	 void load_file(const char* path);

	 /// Returns the CO2 value for a given year
	 /** When accessing co2 values outside of the period specified in the file,
	  *  the class will return the co2 value for the first or the last year
	  *  specified.
	  *
	  *  \param year The historical year for which to get the CO2 value
	  */
	 double operator[](int year) const;

     /// Unlike operator[], this does not clamp an unavailable reference year.
     bool contains_year(int year) const {
         return !co2.empty() && year >= first_year &&
             year - first_year < static_cast<int>(co2.size());
     }

private:

	 /// The co2 values from file
	 std::vector<double> co2;

	 /// The first historical year
	 int first_year;
};

#endif // LPJ_GUESS_GLOBALCO2FILE_H

///////////////////////////////////////////////////////////////////////////////////////
/// \file globalco2file.cpp
/// \brief A class for reading in CO2 values from a text file
///
/// \author Joe Siltberg
/// $Date: 2024-07-09 15:27:51 +0200 (Tue, 09 Jul 2024) $
///
/// This Source Code Form is subject to the terms of the Mozilla Public
/// License, v. 2.0. If a copy of the MPL was not distributed with this
/// file, You can obtain one at http://mozilla.org/MPL/2.0/.
///
///////////////////////////////////////////////////////////////////////////////////////









namespace {

// Constant to indicate that the file hasn't been properly loaded
const int BAD_YEAR = std::numeric_limits<int>::min();

}

GlobalCO2File::GlobalCO2File()
		  : first_year(BAD_YEAR) {
}

void GlobalCO2File::load_file(const char* path) {
	 // Reads in atmospheric CO2 concentrations for historical period
	 // from ascii text file with records in format: <year> <co2-value>
	 
	 
	 // Have we already loaded a file?
	 if (first_year != BAD_YEAR) {
		  // Go back to initial state
		  first_year = BAD_YEAR;
		  co2.clear();
	 }
	 
	 int calender_year;
	 double next_co2;
	 
	 FILE* in = fopen(path, "rt");
	 if (!in) {
		  fail("GlobalCO2File::load_file: could not open CO2 file %s for input", 
				 path);
	 }

	 // Read in the values from the file
	 while (readfor(in,"i,f",&calender_year,&next_co2)) {
		  if (first_year == BAD_YEAR) {
				first_year = calender_year;
		  }
		  else if (calender_year != first_year+int(co2.size())) {
				fail("GlobalCO2File::load_file: %s, line %d - bad year specified",
					  path,co2.size()+1);
		  }
		  co2.push_back(next_co2);
	 }

	 if (first_year == BAD_YEAR) {
		  fail("GlobalCO2File::load_file: failed to load from file %s", path);
	 }
	 
	 fclose(in);
}

double GlobalCO2File::operator[](int year) const {
	 if (first_year == BAD_YEAR) {
		  fail("GlobalCO2File::operator[]: "\
				 "Tried to get CO2 value before loading from file!");
	 }

	 if (year < first_year) {
		  return co2.front();
	 }
	 else if (year >= first_year+static_cast<int>(co2.size())) {
/*
		  fail("GlobalCO2File::operator[]: "\
				 "Tried to get CO2 value after last year in file\n"\
				 "Last year: %d, tried to get CO2 for: %d",
				 first_year+co2.size()-1, year);

		  return 0.0; // to avoid compiler warning
*/
		  if (date.day == 0 && year == first_year + static_cast<int>(co2.size()))
			  dprintf("CO2 value for year %d used from year %d and onwards\n",
				  first_year + co2.size() - 1, year);

		  return co2.back();
	 }
	 else {
		  return co2[year-first_year];
	 }
}

struct Gridcell {};
class CFXInput { public:
int extend_climate_startyear=1901, extend_climate_nyears=1, extend_climate=1, climate_recycle_from_year=1902;
int fixed_co2=0, fixed_co2_year=1901, fixed_co2_from_year=1905;
GlobalCO2File co2;

XGenericSpinupData extclim_temp; GridcellOrderedVariable* cf_temp=nullptr;
XGenericSpinupData extclim_prec; GridcellOrderedVariable* cf_prec=nullptr;
XGenericSpinupData extclim_insol; GridcellOrderedVariable* cf_insol=nullptr;
XGenericSpinupData extclim_wetdays; GridcellOrderedVariable* cf_wetdays=nullptr;
XGenericSpinupData extclim_min_temp; GridcellOrderedVariable* cf_min_temp=nullptr;
XGenericSpinupData extclim_max_temp; GridcellOrderedVariable* cf_max_temp=nullptr;
XGenericSpinupData extclim_pres; GridcellOrderedVariable* cf_pres=nullptr;
XGenericSpinupData extclim_specifichum; GridcellOrderedVariable* cf_specifichum=nullptr;
XGenericSpinupData extclim_relhum; GridcellOrderedVariable* cf_relhum=nullptr;
XGenericSpinupData extclim_wind; GridcellOrderedVariable* cf_wind=nullptr;
void load_extclim_data(const GridcellOrderedVariable*, XGenericSpinupData&);
void populate_daily_arrays(Gridcell&);
double co2_value() {

	const int simulation_year = date.get_calendar_year();
	const int co2_year = fixed_co2 && simulation_year >= fixed_co2_from_year
		? fixed_co2_year : simulation_year;
	return co2[co2_year];

}
};
void CFXInput::load_extclim_data(const GuessNC::CF::GridcellOrderedVariable* cf_var,
															 XGenericSpinupData& extclim_data) {
	
	XGenericSpinupData::RawData source;
	extclim_data.years.clear();
	const int count = cf_var->get_timesteps();
	const bool daily = is_daily(cf_var);
	const int first_year = extend_climate_startyear - extend_climate_nyears + 1;
	int timestep = 0;
	// Bounded forward search also permits the first year in the file.
	while (timestep < count && cf_var->get_date_time(timestep).get_year() < first_year)
		++timestep;
	const int days_in_month[] = {31,28,31,30,31,30,31,31,30,31,30,31};
	for (int year = first_year; year <= extend_climate_startyear; ++year) {
		std::vector<double> values;
		for (int month = 1; month <= 12; ++month) {
			const int days = daily ? days_in_month[month-1] : 1;
			for (int day = 1; day <= days; ++day) {
				if (timestep >= count)
					fail("Reference climate period %d..%d is incomplete", first_year, extend_climate_startyear);
				DateTime dt = cf_var->get_date_time(timestep);
				if (dt.get_year() != year || dt.get_month() != month || (daily && dt.get_day() != day))
					fail("Missing or nonconsecutive reference climate date: expected %d-%02d-%02d", year, month, day);
				values.push_back(cf_var->get_value(timestep++));
			}
			// Gregorian source leap days are omitted in the 365-day model cycle.
			if (daily && month == 2 && timestep < count) {
				DateTime dt = cf_var->get_date_time(timestep);
				if (dt.get_year() == year && dt.get_month() == 2 && dt.get_day() == 29)
					++timestep;
			}
		}
		source.push_back(values);
		extclim_data.years.push_back(year);
	}
	extclim_data.get_data_from(source);
}
void CFXInput::populate_daily_arrays(Gridcell& gridcell) {
	// Reconstruct the cycle phase from the calendar, including after restart.
	// Set it BEFORE any daily/monthly variable is read.
	if (extend_climate && date.get_calendar_year() >= climate_recycle_from_year) {
		const int index = (date.get_calendar_year() - climate_recycle_from_year) % extend_climate_nyears;
		extclim_temp.set_year_index(index);
		extclim_prec.set_year_index(index);
		extclim_insol.set_year_index(index);
		if (cf_wetdays) extclim_wetdays.set_year_index(index);
		if (cf_min_temp) extclim_min_temp.set_year_index(index);
		if (cf_max_temp) extclim_max_temp.set_year_index(index);
		if (cf_pres) extclim_pres.set_year_index(index);
		if (cf_specifichum) extclim_specifichum.set_year_index(index);
		if (cf_relhum) extclim_relhum.set_year_index(index);
		if (cf_wind) extclim_wind.set_year_index(index);
	}

}


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
