import { GUIDE_ANCHORS } from "../HowToRead";
import type { GuideAnchor } from "../HowToRead";

// Từ điển thuật ngữ của trang "Cách đọc dự báo": mỗi từ 1–2 câu đời thường, không công thức.
// Nội dung khớp /home/claude/ws/glossary.md (bản gửi chủ sản phẩm). Không có số giá thật.

export interface GlossaryTerm {
  term: string;
  /** Cách gọi khác cũng xuất hiện trên web, để ô lọc tìm được. */
  aka?: string;
  definition: string;
  /** Mục của trang hướng dẫn giải thích kỹ hơn. */
  anchor?: GuideAnchor;
}

export interface GlossaryGroup {
  id: string;
  title: string;
  terms: GlossaryTerm[];
}

export const GLOSSARY: GlossaryGroup[] = [
  {
    id: "man-hinh",
    title: "Trên màn hình dự báo",
    terms: [
      {
        term: "Phiên",
        aka: "phiên giao dịch",
        definition: "Một ngày sàn giao dịch mở cửa. Cuối tuần và ngày lễ của sàn không tính là phiên.",
        anchor: GUIDE_ANCHORS.horizon,
      },
      {
        term: "Sau h phiên",
        aka: "h, kỳ hạn, h = 1…7",
        definition:
          "Dự báo cho thời điểm cách phiên gần nhất h phiên giao dịch. “Sau 7 phiên” thường rơi vào khoảng một tuần rưỡi lịch.",
        anchor: GUIDE_ANCHORS.horizon,
      },
      {
        term: "Phiên gần nhất",
        aka: "giá cuối, ngày dự báo",
        definition:
          "Phiên mới nhất đã có giá đóng cửa; mọi dự báo tính từ giá của phiên này. Trên biểu đồ là vạch dọc nét đứt.",
        anchor: GUIDE_ANCHORS.chart,
      },
      {
        term: "Giá cuối phiên",
        aka: "giá đóng cửa",
        definition: "Giá chốt lúc phiên kết thúc. Web chỉ dùng giá cuối phiên, không có giá trong ngày.",
      },
      {
        term: "Khoảng 80%",
        aka: "khoảng giá, khoảng dự báo",
        definition:
          "Khoảng giá dự báo đặt ra với mục tiêu chứa giá thật khoảng 8 trong 10 lần. Đây là mục tiêu, chưa phải xác suất đã được kiểm chứng.",
        anchor: GUIDE_ANCHORS.interval,
      },
      {
        term: "Mức giữa",
        aka: "trung vị, q50",
        definition: "Điểm chính giữa của khoảng dự báo, chia dự báo thành nửa thấp và nửa cao. Không phải mức giá chắc chắn sẽ đạt.",
        anchor: GUIDE_ANCHORS.interval,
      },
      {
        term: "Xác suất tăng",
        definition:
          "Dự báo ước lượng khả năng giá sau h phiên cao hơn giá phiên gần nhất là bao nhiêu phần trăm. 50% nghĩa là hoàn toàn chưa rõ.",
        anchor: GUIDE_ANCHORS.probUp,
      },
      {
        term: "“≥ 95%” và “≤ 5%”",
        definition: "Web không ghi chắc hơn 95% hay thấp hơn 5%, vì dự báo không đủ cơ sở để nói chắc hơn thế.",
        anchor: GUIDE_ANCHORS.probUp,
      },
      {
        term: "Nghiêng tăng / Nghiêng giảm / Chưa rõ xu hướng",
        aka: "nhãn hướng",
        definition:
          "Nhãn tóm tắt xác suất tăng: từ 60% là ▲ Nghiêng tăng, từ 40% trở xuống là ▼ Nghiêng giảm, ở giữa là ◆ Chưa rõ xu hướng. Nhãn luôn ghi kèm số phiên.",
        anchor: GUIDE_ANCHORS.probUp,
      },
      {
        term: "Mốc thống kê 252 phiên",
        aka: "baseline-q252",
        definition:
          "Cách dự báo đang dùng: dựa vào mức giá đã lên xuống trong khoảng một năm giao dịch gần nhất (252 phiên). Chưa dùng mô hình học máy và không đọc tin tức.",
        anchor: GUIDE_ANCHORS.baseline,
      },
      {
        term: "Chấm đỏ trên biểu đồ",
        definition: "Mức giữa của dự báo cho từng phiên. Màu đỏ ở đây không có nghĩa là giảm.",
        anchor: GUIDE_ANCHORS.chart,
      },
      {
        term: "Dải xanh trên biểu đồ",
        definition: "Khoảng 80% của từng phiên tới. Dải loe rộng dần vì càng xa càng khó đoán.",
        anchor: GUIDE_ANCHORS.chart,
      },
      {
        term: "Chế độ Cơ bản / Nâng cao",
        definition:
          "Cơ bản hiện những gì cần để đọc nhanh. Nâng cao hiện thêm bảng q10/q50/q90 theo từng phiên, biểu đồ quạt % thay đổi và bảng đếm theo h ở trang Độ chính xác.",
        anchor: GUIDE_ANCHORS.modes,
      },
      {
        term: "Dữ liệu mẫu",
        definition: "Số liệu dựng sẵn để xem thử giao diện, không phải dự báo thật. Luôn có nhãn vàng “Dữ liệu mẫu”.",
      },
      {
        term: "Dữ liệu chưa mới",
        definition: "Nhãn báo dự báo chưa được cập nhật theo phiên mới nhất, thường do nguồn dữ liệu bị lỗi tạm thời.",
      },
    ],
  },
  {
    id: "nang-cao",
    title: "Chế độ Nâng cao",
    terms: [
      {
        term: "Phân vị",
        aka: "q05, q10, q25, q50, q75, q90, q95",
        definition:
          "Các mốc xếp từ thấp đến cao trong dự báo. Số sau chữ q cho biết mốc đứng ở đâu: q10 gần đáy, q50 ở giữa, q90 gần đỉnh.",
        anchor: GUIDE_ANCHORS.quantiles,
      },
      {
        term: "q10 và q90",
        definition: "Mép dưới và mép trên của khoảng 80%.",
        anchor: GUIDE_ANCHORS.quantiles,
      },
      {
        term: "q05 và q95",
        aka: "khoảng 90%",
        definition: "Mép của một khoảng rộng hơn (khoảng 90%), hiện nhạt hơn trên biểu đồ quạt.",
        anchor: GUIDE_ANCHORS.quantiles,
      },
      {
        term: "Log return",
        aka: "% thay đổi",
        definition:
          "Tên kỹ thuật của mức thay đổi giá so với phiên gần nhất. Với thay đổi nhỏ, đọc như % thay đổi quen thuộc: +1,0% là cao hơn khoảng 1%.",
        anchor: GUIDE_ANCHORS.logReturn,
      },
      {
        term: "Biểu đồ quạt",
        definition:
          "Biểu đồ % thay đổi theo số phiên tới; đường 0% là giá không đổi. Quạt loe ra vì càng xa càng khó đoán.",
        anchor: GUIDE_ANCHORS.logReturn,
      },
    ],
  },
  {
    id: "do-tin-cay",
    title: "Độ tin cậy và Độ chính xác",
    terms: [
      {
        term: "Độ tin cậy 8 tuần",
        definition:
          "Phần chấm điểm: lấy các dự báo đã đưa ra trong 8 tuần gần nhất so với giá thật xảy ra sau đó.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Cặp đã chấm",
        aka: "lần đã chấm",
        definition: "Một lần so sánh: một ngày dự báo với một số phiên h mà giá thật đã có. Chưa có giá thật thì chưa chấm.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Đang thu thập (X/20)",
        definition:
          "Đã chấm được X ngày dự báo, cần đủ số ngày tối thiểu (hiện là 20) mới hiện con số chung. Trước đó chưa kết luận gì.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Chưa có kết quả đánh giá",
        definition: "Hệ thống chưa có lượt chấm hoàn chỉnh nào cho cách dự báo đang dùng, nên chưa có số để hiện.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Giá thật nằm trong khoảng 80%",
        aka: "tỷ lệ trong khoảng",
        definition: "Phần trăm số lần giá thật rơi vào khoảng 80%. Gần 80% là khoảng rộng vừa phải.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Trong khoảng 80% X/Y theo h",
        definition:
          "Trong Y lần đã có giá thật sau h phiên, có X lần giá thật nằm trong khoảng 80%. Kỳ vọng khoảng 8 phần 10.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Độ rộng khoảng 80%",
        definition: "Khoảng 80% trung bình rộng bao nhiêu phần trăm giá. Cùng mức trúng, khoảng hẹp hơn cho biết nhiều hơn.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Đúng chiều tăng/giảm",
        definition: "Tỷ lệ lần mức giữa của dự báo đoán đúng giá sẽ lên hay xuống. Luôn đọc cùng tỷ lệ phiên tăng thực tế.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Tỷ lệ phiên tăng thực tế",
        definition:
          "Tỷ lệ lần giá thật đã tăng trong cùng giai đoạn, để biết bối cảnh. Hai tỷ lệ có thể dùng mẫu khác nhau nên không trừ cho nhau.",
        anchor: GUIDE_ANCHORS.reliability,
      },
      {
        term: "Kể từ <ngày>",
        definition: "Ngày dự báo đầu tiên được tính vào phần chấm điểm.",
      },
      {
        term: "Kiểm định lịch sử 2019",
        definition:
          "Lần chạy thử cách dự báo trên dữ liệu năm 2019, ghi ở trang Giới thiệu. Tách riêng, không so thẳng với số chấm 8 tuần.",
      },
    ],
  },
  {
    id: "gia-tien",
    title: "Giá, đơn vị và nguồn",
    terms: [
      {
        term: "Chuỗi đại diện GLD, SLV",
        definition:
          "Hai quỹ nắm giữ vàng, bạc thật. Web theo dõi giá hai quỹ này rồi quy về mức tương đương một ounce, nên gọi là giá quy đổi.",
        anchor: GUIDE_ANCHORS.sources,
      },
      {
        term: "Giá quy đổi",
        definition: "Giá vàng, bạc tính lại từ giá quỹ GLD/SLV. Đi gần giá thế giới nhưng không phải giá giao ngay.",
        anchor: GUIDE_ANCHORS.sources,
      },
      {
        term: "Ounce (oz)",
        aka: "USD/oz",
        definition: "Đơn vị cân vàng, bạc quốc tế, khoảng 31,1 gam.",
        anchor: GUIDE_ANCHORS.vnd,
      },
      {
        term: "Lượng (cây)",
        aka: "VND/lượng",
        definition: "Đơn vị vàng ở Việt Nam, 37,5 gam, tức khoảng 1,2 ounce.",
        anchor: GUIDE_ANCHORS.vnd,
      },
      {
        term: "Thùng",
        aka: "USD/thùng",
        definition: "Đơn vị đo dầu thô, khoảng 159 lít.",
      },
      {
        term: "Dầu Brent và dầu WTI",
        definition: "Hai loại dầu thô chuẩn của thế giới: Brent từ Biển Bắc, WTI từ Mỹ. Giá hai loại thường đi cùng chiều.",
      },
      {
        term: "Hợp đồng tương lai",
        aka: "CL=F, BZ=F",
        definition: "Thỏa thuận mua bán dầu giao vào tháng sau. Giá dầu trên web là giá loại hợp đồng gần nhất.",
        anchor: GUIDE_ANCHORS.roll,
      },
      {
        term: "Đáo hạn hợp đồng",
        definition:
          "Lúc hợp đồng dầu tháng này hết hạn và chuỗi giá chuyển sang hợp đồng tháng sau; giá có thể nhảy một bước dù thị trường không đổi nhiều.",
        anchor: GUIDE_ANCHORS.roll,
      },
      {
        term: "Tỷ giá USD/VND",
        definition: "Tỷ giá của ngày dự báo, chỉ dùng để đổi giá sang tiền Việt; web ghi kèm ngày của tỷ giá.",
        anchor: GUIDE_ANCHORS.vnd,
      },
      {
        term: "Quy đổi ra số tiền",
        aka: "giá trị giả định",
        definition:
          "Bạn nhập số tiền, web cho biết số tiền đó thành bao nhiêu nếu giá đi đúng mép dưới, mức giữa hoặc mép trên của dự báo. Chỉ là giá trị giả định.",
        anchor: GUIDE_ANCHORS.vnd,
      },
      {
        term: "Nguồn: Yahoo Finance, U.S. EIA",
        definition: "Nơi lấy dữ liệu giá: Yahoo Finance cho giá quỹ, dầu và tỷ giá; Cơ quan Thông tin Năng lượng Mỹ (EIA) để đối chiếu giá dầu.",
        anchor: GUIDE_ANCHORS.sources,
      },
    ],
  },
];

/** Bỏ dấu tiếng Việt và chữ hoa để ô lọc gõ "khoang" vẫn ra "Khoảng". */
export function foldText(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
}

export function filterGlossary(query: string): GlossaryGroup[] {
  const needle = foldText(query.trim());
  if (!needle) return GLOSSARY;
  return GLOSSARY.map((group) => ({
    ...group,
    terms: group.terms.filter((item) => foldText(`${item.term} ${item.aka ?? ""} ${item.definition}`).includes(needle)),
  })).filter((group) => group.terms.length > 0);
}
