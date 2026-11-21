# 全域多模态舆情采研算法与技术对账手册 (Methodology Reference)

## 1. 弹幕高能波形与密度计算 (Danmaku Spike Detection)

### 算法流程：
1. **时间轴分桶 (Bucketizing)**：
   将视频全量弹幕中的 `time` 属性按 $w = 5.0$ 秒的时间跨度划入时间桶中：
   $$b_i = \left\lfloor \frac{t_{\text{danmaku}}}{w} \right\rfloor$$
2. **密度统计与正态阈值**：
   计算所有非空时间桶的弹幕数量分布，求均值 $\mu$ 与样本标准差 $\sigma$：
   $$\mu = \frac{1}{N} \sum_{i=1}^N D_i, \quad \sigma = \sqrt{\frac{1}{N} \sum_{i=1}^N (D_i - \mu)^2}$$
3. **峰值门禁判定**：
   $$T_{\text{spike}} = \max(\mu + 2.0\sigma, 8.0)$$
   凡 $D_i \ge T_{\text{spike}}$ 的时段，判定为高能情绪突变时刻。
4. **情感特征词频统计**：
   在峰值时段内，提取与预设情感词库（翻车、发热、退货、劝退、卡顿、死机、真香等）交集的最高频词，形成观众情绪画像。

---

## 2. Jaccard 字符 3-Gram 水军去噪 (Anti-Shill De-noising)

### 算法流程：
1. **去符号化与 Shingling**：
   去除文本中所有非文字与数字字符，按 3 个连续字符切分集合：
   $$\text{Text} \to S = \{c_1 c_2 c_3, c_2 c_3 c_4, \dots\}$$
2. **两两 Jaccard 相似度**：
   $$J(S_A, S_B) = \frac{|S_A \cap S_B|}{|S_A \cup S_B|}$$
3. **聚类与告警门禁**：
   若 $J(S_A, S_B) \ge 0.80$ 且属于不同作者账号：
   - 累加至同一模板集群；
   - 当集群样本数 $\ge 3$ 时，标记为水军控评刷屏，剔除出真实口碑均值统计。

---

## 3. 楼中楼争议反转系数 (Controversy Ratio & Debate Index)

### 计算公式：
1. **争议比率 (Controversy Ratio)**：
   $$\text{Controversy Ratio} = \frac{\text{Replies Count}}{\max(\text{Likes Count}, 1)}$$
   当比值显著偏高（例如赞只有几十，回复却有上百），表明评论引发了强烈的对立与反驳。
2. **综合交锋热度 (Debate Index)**：
   $$\text{Debate Index} = \text{Replies Count} \times \log_{10}(1 + \text{Likes Count})$$
   兼顾了公域曝光度与下潜讨论深度，选出最具代表性的网友反转楼层。
