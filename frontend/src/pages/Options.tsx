import { Layers } from "lucide-react";
import { useLive } from "../context/LiveContext";
import { SpotCard } from "../components/market/MarketCards";
import { Card, Pill, Stat } from "../components/common/Card";
import { PageHeader } from "../components/common/Controls";
import { Empty, Limitation, Loading } from "../components/common/States";
import { dmy, hms, num } from "../utils/format";

/**
 * Options analysis built only from what the backend exposes: the strategy's verified
 * recommended contract. There is no option-chain or expiry-list endpoint yet (see docs/TODO.md).
 */
export default function Options() {
  const { data } = useLive();
  if (!data) return <Loading />;
  const sig = data.feed?.signal;
  const rec = sig?.rec;
  const spot = data.feed?.quote?.price;
  const verified = rec?.verified;
  const moneyness = verified && spot != null && rec?.strike != null
    ? (rec.opt_type === "CE" ? spot - rec.strike : rec.strike - spot) : null;

  return (
    <div className="space-y-4">
      <PageHeader title="Options Analysis" subtitle="Spot (the index) and premium (the contract's own price) are always shown separately." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SpotCard data={data} />
        <Card title="Selected contract" icon={<Layers size={16} className="text-violet-600" />} className="lg:col-span-2"
          right={verified ? <Pill tone={rec!.opt_type === "CE" ? "good" : "bad"}>{rec!.opt_type === "CE" ? "CALL" : "PUT"}</Pill> : undefined}>
          {!rec || sig?.action === "HOLD" ? (
            <Empty title="No contract selected">The strategy says HOLD. A contract is chosen and verified only when it signals BUY CE or BUY PE.</Empty>
          ) : !verified ? (
            <p className="text-sm text-orange-600">{rec.error ?? "The contract could not be verified."}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr><th className="py-2">Contract</th><th>Strike</th><th>Expiry</th><th className="text-right">Premium</th><th className="text-right">Chain LTP</th><th className="text-right">OI</th><th className="text-right">IV</th><th className="text-right">Delta</th></tr>
                  </thead>
                  <tbody>
                    <tr className="bg-violet-50 font-medium dark:bg-violet-950/30">
                      <td className="py-2 pl-1"><span className="num text-xs">{rec!.symbol}</span></td>
                      <td className="num">{num(rec!.strike, 0)} {rec!.opt_type}</td>
                      <td>{dmy(rec!.expiry)}</td>
                      <td className="num text-right">₹{num(rec!.premium)}</td>
                      <td className="num text-right">{rec!.chain_ltp != null ? `₹${num(rec!.chain_ltp)}` : "—"}</td>
                      <td className="num text-right">{rec!.oi != null ? num(rec!.oi, 0) : "—"}</td>
                      <td className="num text-right">{rec!.iv != null ? num(rec!.iv, 1) : "—"}</td>
                      <td className="num pr-1 text-right">{rec!.delta != null ? num(rec!.delta, 2) : "—"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Strike rule" value={rec!.strike_rule ?? "—"} />
                <Stat label="Moneyness" value={moneyness == null ? "—" : moneyness >= 0 ? `ITM by ${num(moneyness, 0)}` : `OTM by ${num(-moneyness, 0)}`}
                  tip="How far the strike is in or out of the money versus the NIFTY spot." />
                <Stat label="Lot size" value={rec!.lot_size ?? "—"} />
                <Stat label="Quote time" value={hms(rec!.quote_as_of)} />
              </div>
            </>
          )}
        </Card>
      </div>
      <Card title="Option chain">
        <Limitation>
          Not available yet: the backend has no option-chain or expiry-list endpoint for the frontend. It reads the chain internally to verify the
          recommended contract, which is shown above. Volume and premium change aren't provided either. A chain endpoint is listed in docs/TODO.md;
          until it exists, this page shows no other strikes rather than made-up ones.
        </Limitation>
      </Card>
    </div>
  );
}
