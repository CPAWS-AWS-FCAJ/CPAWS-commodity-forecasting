import { useId, useState } from "react";
import { GUIDE_ANCHORS } from "../HowToRead";
import { filterGlossary, GLOSSARY } from "./glossaryTerms";

const TOTAL = GLOSSARY.reduce((sum, group) => sum + group.terms.length, 0);

/** "Từ điển thuật ngữ": nhóm theo chỗ người dùng gặp từ đó, có ô lọc nhanh (không phân biệt dấu). */
export function Glossary() {
  const [query, setQuery] = useState("");
  const inputId = useId();
  const groups = filterGlossary(query);
  const found = groups.reduce((sum, group) => sum + group.terms.length, 0);
  const id = GUIDE_ANCHORS.glossary;

  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 border-t border-line pt-10 lg:scroll-mt-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id={`${id}-title`} className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">
            Từ điển thuật ngữ
          </h2>
          <p className="mt-2 text-base text-muted">{TOTAL} từ bạn gặp trên web, mỗi từ giải thích trong 1–2 câu.</p>
        </div>
        <div className="w-full sm:w-72">
          <label htmlFor={inputId} className="text-sm font-medium">
            Tìm từ
          </label>
          <input
            id={inputId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ví dụ: phiên, khoảng 80%"
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-base text-price placeholder:text-muted focus-visible:border-forecast focus-visible:outline-2 focus-visible:outline-forecast motion-safe:transition-colors"
          />
        </div>
      </div>

      <p role="status" className="mt-3 text-sm text-muted">
        {query.trim() ? (found ? `${found} từ khớp “${query.trim()}”` : `Không có từ nào khớp “${query.trim()}”`) : ""}
      </p>

      <div className="mt-4 space-y-10">
        {groups.map((group) => (
          <div key={group.id}>
            <h3 className="text-lg font-semibold">{group.title}</h3>
            <dl className="mt-3 grid gap-x-8 md:grid-cols-2">
              {group.terms.map((item) => (
                <div key={item.term} className="border-t border-line py-4">
                  <dt className="text-base font-semibold sm:text-[17px]">
                    {item.term}
                    {item.aka ? <span className="ml-2 text-sm font-normal text-muted">({item.aka})</span> : null}
                  </dt>
                  <dd className="mt-1 text-base leading-relaxed">
                    {item.definition}
                    {item.anchor ? (
                      <>
                        {" "}
                        <a href={`#${item.anchor}`} className="whitespace-nowrap text-sm text-forecast underline underline-offset-2">
                          Xem mục<span className="sr-only"> giải thích {item.term}</span>
                        </a>
                      </>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}
