import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BigValue, Card, Dot, InfoTip, Pill, Stat } from "../../components/common/Card";
import { Button, Field, PageHeader, Segmented } from "../../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress, Warning } from "../../components/common/States";

describe("Card", () => {
  it("renders a titled section with a right-hand slot and body", () => {
    render(<Card title="Spot" right={<span>as of 10:15</span>}>body text</Card>);
    expect(screen.getByRole("heading", { level: 2, name: "Spot" })).toBeInTheDocument();
    expect(screen.getByText("as of 10:15")).toBeInTheDocument();
    expect(screen.getByText("body text")).toBeInTheDocument();
  });

  it("omits the header when it has neither title nor right slot", () => {
    render(<Card>only body</Card>);
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("marks the card with its accent colour bar", () => {
    const { container } = render(<Card accent="gain" title="x">y</Card>);
    expect(container.querySelector("section")?.className).toContain("before:bg-green-500");
  });
});

describe("Stat and InfoTip", () => {
  it("shows label, value and sub text", () => {
    render(<Stat label="Entry" value="₹120" sub="best offer" />);
    expect(screen.getByText("Entry")).toBeInTheDocument();
    expect(screen.getByText("₹120")).toBeInTheDocument();
    expect(screen.getByText("best offer")).toBeInTheDocument();
  });

  it("exposes the tip as an accessible, keyboard-focusable explanation", () => {
    render(<Stat label="Gap" value="20" tip="Positive means bullish." />);
    const tip = screen.getByLabelText("Positive means bullish.");
    expect(tip).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent("Positive means bullish.");
  });

  it("InfoTip works on its own", () => {
    render(<InfoTip text="Hello" />);
    expect(screen.getByLabelText("Hello")).toBeInTheDocument();
  });
});

describe("Pill, Dot, BigValue", () => {
  it("applies the tone colours", () => {
    render(<><Pill tone="good">UP</Pill><Pill tone="bad">DOWN</Pill><Pill>FLAT</Pill></>);
    expect(screen.getByText("UP").className).toContain("bg-green-100");
    expect(screen.getByText("DOWN").className).toContain("bg-red-100");
    expect(screen.getByText("FLAT").className).toContain("bg-slate-100");
  });

  it("Dot pulses only when asked", () => {
    const { container, rerender } = render(<Dot tone="good" />);
    expect(container.querySelector(".animate-ping")).toBeNull();
    rerender(<Dot tone="good" pulse />);
    expect(container.querySelector(".animate-ping")).not.toBeNull();
  });

  it("BigValue shows the headline and its sub line", () => {
    render(<BigValue value="25,000.50" sub="+0.5%" />);
    expect(screen.getByText("25,000.50")).toBeInTheDocument();
    expect(screen.getByText("+0.5%")).toBeInTheDocument();
  });
});

describe("Segmented", () => {
  const options = [{ value: 5, label: "5m" }, { value: 15, label: "15m" }, { value: 30, label: "30m" }];

  it("is a radio group whose checked item follows the value", () => {
    render(<Segmented value={15} options={options} onChange={() => {}} />);
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "15m" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "5m" })).toHaveAttribute("aria-checked", "false");
  });

  it("reports the clicked value", async () => {
    const onChange = vi.fn();
    render(<Segmented value={5} options={options} onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "30m" }));
    expect(onChange).toHaveBeenCalledWith(30);
  });

  it("does nothing when disabled", async () => {
    const onChange = vi.fn();
    render(<Segmented value={5} options={options} onChange={onChange} disabled />);
    await userEvent.click(screen.getByRole("radio", { name: "30m" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("uses a red highlight for the dangerous option (Live)", () => {
    render(<Segmented value="live" options={[{ value: "paper", label: "Paper" }, { value: "live", label: "Live", tone: "danger" }]} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "Live" }).className).toContain("bg-red-600");
  });
});

describe("Button, Field, PageHeader", () => {
  it("fires onClick, but not when disabled", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Go</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(<Button onClick={onClick} disabled>Go</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("submits forms only when type=submit", async () => {
    const onSubmit = vi.fn((e) => e.preventDefault());
    render(<form onSubmit={onSubmit}><Button>plain</Button><Button type="submit">send</Button></form>);
    await userEvent.click(screen.getByRole("button", { name: "plain" }));
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("Field associates its label with the input", async () => {
    render(<Field label="Capital"><input /></Field>);
    await userEvent.type(screen.getByLabelText("Capital"), "5000");
    expect(screen.getByLabelText("Capital")).toHaveValue("5000");
  });

  it("PageHeader shows title, subtitle and actions", () => {
    render(<PageHeader title="Backtesting" subtitle="Real prices" actions={<button>Run</button>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Backtesting" })).toBeInTheDocument();
    expect(screen.getByText("Real prices")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
  });
});

describe("loading, empty and error states", () => {
  it("Loading shows its text", () => {
    render(<Loading text="Fetching…" />);
    expect(screen.getByText("Fetching…")).toBeInTheDocument();
  });

  it("Empty explains what to do next", () => {
    render(<Empty title="No trades">Download data first.</Empty>);
    expect(screen.getByText("No trades")).toBeInTheDocument();
    expect(screen.getByText("Download data first.")).toBeInTheDocument();
  });

  it("ErrorNote is announced to assistive tech", () => {
    render(<ErrorNote>Backend unreachable</ErrorNote>);
    expect(screen.getByRole("alert")).toHaveTextContent("Backend unreachable");
  });

  it("Warning and Limitation render their message", () => {
    render(<><Warning>Groww feed: timeout</Warning><Limitation>Not provided by Groww</Limitation></>);
    expect(screen.getByText("Groww feed: timeout")).toBeInTheDocument();
    expect(screen.getByText("Not provided by Groww")).toBeInTheDocument();
  });

  it("Progress clamps the bar between 0 and 100%", () => {
    const { container, rerender } = render(<Progress value={0.456} text="Downloading" />);
    const bar = () => container.querySelector<HTMLElement>(".bg-blue-500")!;
    expect(bar().style.width).toBe("46%");
    expect(screen.getByText("Downloading")).toBeInTheDocument();
    rerender(<Progress value={7} />);
    expect(bar().style.width).toBe("100%");
    rerender(<Progress value={-3} />);
    expect(bar().style.width).toBe("0%");
  });
});
