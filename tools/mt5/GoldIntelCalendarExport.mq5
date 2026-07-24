#property copyright "Gold Market Intelligence Engine"
#property version   "1.00"
#property strict
#property script_show_inputs

// Read-only MetaTrader 5 economic-calendar exporter.
//
// The script reads MetaQuotes calendar history and writes an immutable raw CSV
// into the terminal-wide Common\Files sandbox. It does not inspect credentials,
// place orders, modify positions, or enable automated trading.

input datetime InpDateFrom = D'2021.07.23 00:00:00';
input datetime InpDateTo = D'2026.07.25 00:00:00';
input string   InpCountryCode = "US";
input int      InpChunkDays = 180;
input string   InpOutputFile = "GoldIntel\\mt5_us_calendar_raw.csv";
input string   InpStatusFile = "GoldIntel\\mt5_us_calendar_status.csv";

string OptionalNumber(const bool present, const double value, const uint digits)
  {
   if(!present)
      return "";

   int safe_digits=(int)MathMin((double)digits,10.0);
   return DoubleToString(value,safe_digits);
  }

bool WriteStatus(const int rows_written,
                 const int chunks_succeeded,
                 const int chunks_failed,
                 const int last_error)
  {
   int handle=FileOpen(InpStatusFile,
                       FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,
                       ',',
                       CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("GoldIntel calendar export could not open status file '%s'; error=%d",
                  InpStatusFile,
                  GetLastError());
      return false;
     }

   FileWrite(handle,
             "schema_version",
             "completed_at_server",
             "completed_at_gmt",
             "current_server_utc_offset_seconds",
             "terminal_build",
             "date_from_server",
             "date_to_server",
             "country_code",
             "output_file",
             "rows_written",
             "chunks_succeeded",
             "chunks_failed",
             "last_error");
   FileWrite(handle,
             "1.0",
             TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),
             TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),
             (long)(TimeTradeServer()-TimeGMT()),
             (long)TerminalInfoInteger(TERMINAL_BUILD),
             TimeToString(InpDateFrom,TIME_DATE|TIME_SECONDS),
             TimeToString(InpDateTo,TIME_DATE|TIME_SECONDS),
             InpCountryCode,
             InpOutputFile,
             rows_written,
             chunks_succeeded,
             chunks_failed,
             last_error);
   FileFlush(handle);
   FileClose(handle);
   return true;
  }

void OnStart()
  {
   if(InpDateFrom<=0 || InpDateTo<=InpDateFrom)
     {
      Print("GoldIntel calendar export rejected an invalid date interval.");
      WriteStatus(0,0,1,4001);
      return;
     }
   if(InpChunkDays<1 || InpChunkDays>366)
     {
      Print("GoldIntel calendar export requires InpChunkDays between 1 and 366.");
      WriteStatus(0,0,1,4002);
      return;
     }
   if(StringLen(InpCountryCode)!=2)
     {
      Print("GoldIntel calendar export requires a two-character ISO country code.");
      WriteStatus(0,0,1,4003);
      return;
     }

   FolderCreate("GoldIntel",FILE_COMMON);
   ResetLastError();
   int handle=FileOpen(InpOutputFile,
                       FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,
                       ',',
                       CP_UTF8);
   if(handle==INVALID_HANDLE)
     {
      int open_error=GetLastError();
      PrintFormat("GoldIntel calendar export could not open '%s'; error=%d",
                  InpOutputFile,
                  open_error);
      WriteStatus(0,0,1,open_error);
      return;
     }

   FileWrite(handle,
             "schema_version",
             "exported_at_server",
             "exported_at_gmt",
             "current_server_utc_offset_seconds",
             "terminal_build",
             "chunk_from_server",
             "chunk_to_server",
             "value_id",
             "event_id",
             "event_time_server",
             "observation_period_server",
             "revision",
             "actual_value",
             "previous_value",
             "revised_previous_value",
             "forecast_value",
             "impact_type",
             "event_type",
             "sector",
             "frequency",
             "time_mode",
             "country_id",
             "country_code",
             "country_name",
             "currency",
             "unit",
             "importance",
             "multiplier",
             "digits",
             "event_code",
             "event_name",
             "source_url");

   const datetime export_server_time=TimeTradeServer();
   const datetime export_gmt_time=TimeGMT();
   const long server_utc_offset=(long)(export_server_time-export_gmt_time);
   const long terminal_build=(long)TerminalInfoInteger(TERMINAL_BUILD);
   const long chunk_seconds=(long)InpChunkDays*86400;
   datetime cursor=InpDateFrom;
   int rows_written=0;
   int chunks_succeeded=0;
   int chunks_failed=0;
   int last_error=0;

   while(cursor<InpDateTo)
     {
      datetime chunk_to=(datetime)MathMin((double)InpDateTo,
                                          (double)((long)cursor+chunk_seconds));
      MqlCalendarValue values[];
      ResetLastError();
      int value_count=CalendarValueHistory(values,
                                           cursor,
                                           chunk_to,
                                           InpCountryCode);
      if(value_count<0)
        {
         last_error=GetLastError();
         chunks_failed++;
         PrintFormat("GoldIntel calendar chunk failed: %s through %s; error=%d",
                     TimeToString(cursor,TIME_DATE|TIME_SECONDS),
                     TimeToString(chunk_to,TIME_DATE|TIME_SECONDS),
                     last_error);
         cursor=chunk_to;
         continue;
        }

      chunks_succeeded++;
      for(int index=0; index<value_count; index++)
        {
         MqlCalendarEvent event;
         ResetLastError();
         if(!CalendarEventById(values[index].event_id,event))
           {
            last_error=GetLastError();
            continue;
           }

         MqlCalendarCountry country;
         string country_code=InpCountryCode;
         string country_name="";
         string currency="";
         if(CalendarCountryById(event.country_id,country))
           {
            country_code=country.code;
            country_name=country.name;
            currency=country.currency;
           }

         FileWrite(handle,
                   "1.0",
                   TimeToString(export_server_time,TIME_DATE|TIME_SECONDS),
                   TimeToString(export_gmt_time,TIME_DATE|TIME_SECONDS),
                   server_utc_offset,
                   terminal_build,
                   TimeToString(cursor,TIME_DATE|TIME_SECONDS),
                   TimeToString(chunk_to,TIME_DATE|TIME_SECONDS),
                   values[index].id,
                   values[index].event_id,
                   TimeToString(values[index].time,TIME_DATE|TIME_SECONDS),
                   TimeToString(values[index].period,TIME_DATE|TIME_SECONDS),
                   values[index].revision,
                   OptionalNumber(values[index].HasActualValue(),
                                  values[index].GetActualValue(),
                                  event.digits),
                   OptionalNumber(values[index].HasPreviousValue(),
                                  values[index].GetPreviousValue(),
                                  event.digits),
                   OptionalNumber(values[index].HasRevisedValue(),
                                  values[index].GetRevisedValue(),
                                  event.digits),
                   OptionalNumber(values[index].HasForecastValue(),
                                  values[index].GetForecastValue(),
                                  event.digits),
                   (int)values[index].impact_type,
                   (int)event.type,
                   (int)event.sector,
                   (int)event.frequency,
                   (int)event.time_mode,
                   event.country_id,
                   country_code,
                   country_name,
                   currency,
                   (int)event.unit,
                   (int)event.importance,
                   (int)event.multiplier,
                   event.digits,
                   event.event_code,
                   event.name,
                   event.source_url);
         rows_written++;
        }

      FileFlush(handle);
      cursor=chunk_to;
     }

   FileFlush(handle);
   FileClose(handle);
   WriteStatus(rows_written,chunks_succeeded,chunks_failed,last_error);

   PrintFormat("GoldIntel calendar export completed: rows=%d, chunks_ok=%d, chunks_failed=%d, file=%s",
               rows_written,
               chunks_succeeded,
               chunks_failed,
               InpOutputFile);
  }
