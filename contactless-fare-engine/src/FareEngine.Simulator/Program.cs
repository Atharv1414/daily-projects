using System.Globalization;
using FareEngine.Simulator;

var cards = Arg(0, 1000);
var weeks = Arg(1, 4);
var seed = Arg(2, 42);
Console.OutputEncoding = System.Text.Encoding.UTF8;
CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
Console.WriteLine($"Simulating {cards:N0} cards for {weeks} weeks (seed {seed})");
var r = await Simulation.RunAsync(cards, weeks, seed);

Console.WriteLine($"""

    Delivered          {r.Deliveries,10:N0} taps, in the order they arrived
      stored once      {r.StoredTaps,10:N0}
      retries ignored  {r.Duplicates,10:N0}
    Journeys
      auto-completed   {r.AutoCompleted,10:N0}
      incomplete       {r.Incomplete,10:N0} charged the maximum fare
    Money
      single fares     {r.Gross,12}
      charged          {r.Charged,12}  ({(r.Gross - r.Charged).Pence / (double)r.Gross.Pence:P1} saved by caps)
      collected        {r.Collected,12}  over {r.SettledDays} settled days
      refunded         {r.Refunded,12}
    Ledger
      entries          {r.LedgerEntries,10:N0}  of which {r.Adjustments:N0} adjustments for late taps
    Checks
      ledger differs from a clean rating   {r.MismatchedCardWeeks} of {r.CardWeeks:N0} card weeks
      card days above the widest daily cap {r.CardDaysOverCap}
      settled equals charged               {(r.Collected - r.Refunded == r.Charged ? "yes" : "NO")}
    Speed
      ingest           {r.Deliveries / r.IngestTime.TotalSeconds,10:N0} taps per second
      rate             {r.WeeksRated / r.RatingTime.TotalSeconds,10:N0} card weeks per second ({r.WeeksRated:N0} ratings)
    """);

return r.MismatchedCardWeeks == 0 && r.CardDaysOverCap == 0 && r.Collected - r.Refunded == r.Charged ? 0 : 1;

int Arg(int index, int fallback) =>
    args.Length > index ? int.Parse(args[index], CultureInfo.InvariantCulture) : fallback;
