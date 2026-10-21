"""Server-backed quotation analysis. No quotation or document pricing writes."""
from __future__ import annotations

from copy import deepcopy
import json
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QDate, QEvent, QPointF, QRectF, Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabBar, QVBoxLayout, QWidget,
)
from dialog_style import DIALOG_COLORS, button_style, style_dialog
from ui_typography import BODY_PX, FONT_FAMILY_QSS, PAGE_TITLE_PX, TABLE_PX
import quote_scheme_center as schemes
from quote_scheme_widgets import SchemeComboBox, QueryLineEdit

METRICS = {"inset": 16, "gap": 10, "chart_height": 190, "table_row": 38, "field_height": 36,
           "short_window": 1050, "dialog_width": 620}
COLORS = {"bg":"#f3f5f8", "panel":"#ffffff", "brand":"#2563eb", "deep":"#173e76",
          "text":"#243447", "secondary":"#5d7087", "muted":"#8a99aa",
          "border":"#c9d5e2", "soft":"#dce4ec", "head":"#eaf1f8",
          "green":"#79a943", "success":"#3b6d11", "warning":"#955b0a"}
COST_COLORS = ("#2563eb", "#185fa5", "#ef9f27", "#79a943", "#bbd0ea", "#8a8a86")
COST_NAMES = {"material_cost": "材料", "auxiliary_cost": "辅材", "labor_cost": "人工",
              "attachment_fee": "附件", "spray_cost": "喷涂", "management_fee": "管理"}


def number(value, currency=False):
    if value is None:
        return "—"
    return ("¥ " if currency else "") + (f"{float(value):,.2f}" if currency else str(value))


def label(text="", name=""):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def table(headers, name):
    result = QTableWidget(0, len(headers))
    result.setObjectName(name)
    result.setHorizontalHeaderLabels(headers)
    result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    result.setWordWrap(False)
    result.setTextElideMode(Qt.TextElideMode.ElideRight)
    for col,caption in enumerate(headers):result.horizontalHeaderItem(col).setToolTip(caption)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    result.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
    result.horizontalHeader().setMinimumSectionSize(80)
    result.horizontalHeader().setStretchLastSection(True)
    result.verticalHeader().hide()
    result.verticalHeader().setDefaultSectionSize(METRICS["table_row"])
    result.setShowGrid(False)
    result.setMinimumHeight(140)
    return result


def fill(target, rows):
    for row in range(target.rowCount()):
        for col in range(target.columnCount()):
            old=target.cellWidget(row,col)
            if old is not None:
                old.hide()
                target.removeCellWidget(row,col)
    target.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value if value is not None else "—"))
            item.setToolTip(item.text())
            target.setItem(row, col, item)
    for row in range(len(rows)):
        target.setRowHeight(row, METRICS["table_row"])
    target.setFixedHeight(max(90, target.horizontalHeader().height()+sum(target.rowHeight(i) for i in range(min(len(rows),8)))+10))


class AnalysisWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, window, path, payload=None):
        super().__init__(window)
        self.url = schemes._base_url(window) + path
        self.headers = schemes._headers(window)
        self.payload = deepcopy(payload)

    def run(self):
        try:
            headers = {**self.headers, "Accept": "application/json"}
            data = None
            if self.payload is not None:
                data = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            request = urllib.request.Request(self.url, data=data, headers=headers,
                                             method="POST" if data else "GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not self.isInterruptionRequested():
                self.succeeded.emit(value)
        except urllib.error.HTTPError as error:
            if error.code in (404, 405):
                message = "报价分析服务尚未部署，请联系管理员更新 API。现有报价与导出仍可使用。"
            else:
                try:
                    message = json.loads(error.read().decode("utf-8")).get("message") or "报价分析请求失败。"
                except Exception:
                    message = "报价分析请求失败，请稍后重新加载。"
            self.failed.emit(message)
        except Exception:
            self.failed.emit("报价分析连接失败，请检查网络后重新加载。现有填写内容已保留。")


class KpiCard(QPushButton):
    """One shared metric treatment, matching the approved HTML card hierarchy."""
    def __init__(self, caption, note="", compact=False):
        super().__init__(caption+"\n—")
        self.note = note
        self.compact = compact
        self.setObjectName("analysisKpi")
        self.setProperty("compact",compact)
        self.setMinimumWidth(0)
        self.setFixedHeight(86 if compact else 96)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#f8fbff" if self.compact else COLORS["panel"]))
        painter.setPen(QColor(COLORS["brand"] if (self.underMouse() or self.hasFocus()) and self.isEnabled() else COLORS["border"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),6,6)
        caption,_,value = self.text().partition("\n")
        for text, y, size, color, bold in ((caption,10,12,"secondary",False),
                                         (value,29,18 if self.compact else 21,"deep",True),
                                         (self.note,64 if not self.compact else 59,11,"muted",False)):
            font=QFont(self.font());font.setPixelSize(size);font.setBold(bold)
            painter.setFont(font);painter.setPen(QColor(COLORS[color]))
            rect=QRectF(12,y,self.width()-24,30 if y==29 else 19)
            shown=painter.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,int(rect.width()))
            painter.drawText(rect,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,shown)

    def setText(self, text):
        super().setText(text)
        self.setAccessibleName(text.replace("\n","："))
        self.setToolTip(text.replace("\n","："))


class CustomerRankChart(QWidget):
    selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.rows=[]
        self.setFixedHeight(METRICS["chart_height"])
        self.setMinimumWidth(0)
        self.setAccessibleName("客户 Top 5，按正式报价金额；点击客户筛选")

    def set_rows(self, rows):
        self.rows=list(rows)[:5]
        self.setToolTip("\n".join(f"{r['name']}：{number(r['amount'],True)}，{r['count']} 个方案，金额覆盖 {r.get('amount_coverage',r['count'])}/{r['count']}" for r in self.rows))
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font=QFont(self.font());font.setPixelSize(12);p.setFont(font)
        if not self.rows:
            p.setPen(QColor(COLORS['secondary']))
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"当前条件下暂无客户排行")
            return
        maximum=max(1,max(float(r['amount'] or 0) for r in self.rows))
        name_width=min(115,max(70,self.width()*.31))
        value_width=85
        start=26+name_width; width=max(12,self.width()-start-value_width-8)
        for i,r in enumerate(self.rows):
            y=8+i*33
            p.setPen(QColor(COLORS['deep']))
            p.drawText(QRectF(0,y,20,25),str(i+1))
            p.drawText(QRectF(25,y,name_width-5,25),p.fontMetrics().elidedText(r['name'],Qt.TextElideMode.ElideRight,int(name_width-5)))
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#edf1f5'))
            p.drawRoundedRect(QRectF(start,y+9,width,7),3,3)
            p.setBrush(QColor(COLORS['brand'] if i<2 else COLORS['green'] if i<4 else '#d98a2b'))
            p.drawRoundedRect(QRectF(start,y+9,width*float(r['amount'] or 0)/maximum,7),3,3)
            p.setPen(QColor(COLORS['secondary']))
            amount=p.fontMetrics().elidedText(number(r['amount'],True),Qt.TextElideMode.ElideRight,value_width)
            p.drawText(QRectF(start+width+5,y,value_width,25),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,amount)

    def mousePressEvent(self,event):
        index=int((event.position().y()-8)//33)
        if 0<=index<len(self.rows):self.selected.emit(index)


class CostDonut(QWidget):
    selected = Signal()

    def __init__(self):
        super().__init__()
        self.rows=[]
        self.setFixedHeight(METRICS['chart_height'])
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("成本结构，来源于完整的公式法报价快照")

    def set_rows(self, costs):
        self.rows=[(COST_NAMES.get(k,k),float(v)) for k,v in costs.items() if v is not None and float(v)>0]
        self.setToolTip("\n".join(f"{name}：{number(value,True)}" for name,value in self.rows) or '暂无完整成本快照')
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font=QFont(self.font());font.setPixelSize(12);p.setFont(font)
        diameter=min(138,max(95,self.width()*.42))
        rect=QRectF(0,15,diameter,diameter)
        total=sum(v for _,v in self.rows)
        if total:
            angle=90*16
            for i,(_,value) in enumerate(self.rows):
                span=-round(value/total*360*16)
                p.setBrush(QColor(COST_COLORS[i%len(COST_COLORS)]));p.setPen(Qt.PenStyle.NoPen)
                p.drawPie(rect,angle,span);angle+=span
        else:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#eaf1f8'));p.drawEllipse(rect)
        p.setBrush(QColor('white'));p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(rect.adjusted(diameter*.22,diameter*.22,-diameter*.22,-diameter*.22))
        p.setPen(QColor(COLORS['secondary']))
        p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'成本快照\n结构' if total else '暂无完整\n成本快照')
        for i,(name,value) in enumerate(self.rows):
            x=diameter+12;y=16+i*25
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(COST_COLORS[i%len(COST_COLORS)]))
            p.drawRoundedRect(QRectF(x,y+4,8,8),1,1)
            p.setPen(QColor(COLORS['secondary']))
            p.drawText(QRectF(x+13,y,self.width()-x-13,23),f'{name} {value/total*100:.1f}%')

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.selected.emit()


class TrendChart(QWidget):
    """Native, accessible trend chart; values are the returned frozen quote counts."""
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setFixedHeight(METRICS["chart_height"])
        self.setMinimumWidth(0)
        self.setAccessibleName("方案与报价数量趋势：蓝色新建方案，绿色已报价")

    def set_rows(self, rows):
        self.rows = list(rows)
        self.setToolTip("；".join(f"{r['date']}：新建 {r.get('created_count',0)} 个，已报价 {r['count']} 个" for r in rows) or "当前条件下暂无正式报价")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            painter.setPen(QColor(DIALOG_COLORS["text"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "当前条件下暂无正式报价")
            return
        left, top, width, height = 35, 15, max(1, self.width()-55), self.height()-45
        maximum = max(3, max(max(int(r["count"]),int(r.get("created_count",0))) for r in self.rows))
        font=QFont(self.font());font.setPixelSize(11);painter.setFont(font)
        painter.setPen(QColor(COLORS["soft"]))
        for part in range(4):
            y = top + height * part / 3
            painter.drawLine(QPointF(left, y), QPointF(left+width, y))
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(0, int(y+4), str(round(maximum*(1-part/3))))
            painter.setPen(QColor(COLORS["soft"]))
        for key,color in (("created_count",COLORS['brand']),("count",COLORS['green'])):
            points = [QPointF(left+i*width/max(1,len(self.rows)-1), top+height*(1-int(row.get(key,0))/maximum))
                      for i,row in enumerate(self.rows)]
            painter.setPen(QPen(QColor(color), 2))
            for a,b in zip(points,points[1:]):painter.drawLine(a,b)
            if len(points)<=7:
                for point in points:painter.drawEllipse(point,3,3)
        painter.setPen(QColor(COLORS['muted']))
        ticks=sorted(set(round(i*(len(self.rows)-1)/4) for i in range(5)))
        for index in ticks:
            x=left+index*width/max(1,len(self.rows)-1)
            if index==len(self.rows)-1 and index:x-=30
            painter.drawText(int(x),self.height()-5,self.rows[index]["date"][5:])

    def mousePressEvent(self, event):
        if self.rows:
            index = round(max(0,min(1,(event.position().x()-35)/max(1,self.width()-55)))*(len(self.rows)-1))
            self.selected.emit(self.rows[index]["date"])


class AnalysisPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.worker = None
        self.data = None
        self.pending_reload = False
        self._populate = False
        self.setObjectName("quoteAnalysisPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(self.style_sheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*([METRICS["inset"]]*4))
        outer.setSpacing(METRICS["gap"])
        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title_column.addWidget(label("报价分析", "analysisTitle"))
        subtitle=label("报价概览 · 产品折扣与成交表现", "analysisSubtitle")
        subtitle.setWordWrap(False)
        title_column.addWidget(subtitle)
        heading.addLayout(title_column)
        heading.addStretch(1)
        self.record_button = QPushButton("登记成交结果")
        self.record_button.setStyleSheet(button_style("secondary"))
        self.record_button.clicked.connect(self.record_dialog)
        self.record_button.setEnabled(False)
        heading.addWidget(self.record_button)
        outer.addLayout(heading)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(True)
        self.tabs.addTab("报价总览")
        self.tabs.addTab("产品折扣分析")
        outer.addWidget(self.tabs)
        self.content = QWidget()
        content_column = QVBoxLayout(self.content)
        content_column.setContentsMargins(0,0,0,0)
        content_column.setSpacing(METRICS["gap"])
        self.notice = label("数据来源：报价服务器。选择条件后查询。", "analysisNotice")
        content_column.addWidget(self.notice)
        self.filter_card = QFrame()
        self.filter_card.setObjectName("analysisCard")
        filter_column = QVBoxLayout(self.filter_card)
        filter_column.setContentsMargins(12,10,12,10)
        self.filter_layout = QGridLayout()
        self.filter_layout.setHorizontalSpacing(10)
        self.filter_layout.setVerticalSpacing(10)
        filter_column.addLayout(self.filter_layout)
        self.period = SchemeComboBox()
        self.period.addItems(["本月", "本周", "近30天", "全部"])
        self.date_from = QDateEdit(QDate.currentDate().addDays(1-QDate.currentDate().day()))
        self.date_to = QDateEdit(QDate.currentDate())
        for editor in (self.date_from,self.date_to):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
        self.customer = SchemeComboBox()
        self.customer.addItem("全部客户（汇总观察）", "")
        self.product = SchemeComboBox()
        self.product.addItem("全部产品", "")
        self.status = SchemeComboBox()
        self.status.addItem("全部状态", "")
        for code,text in schemes.STATUS_TEXT.items():
            self.status.addItem(text,code)
        self.creator = QueryLineEdit()
        self.creator.returnPressed.connect(self.reload)
        self.creator.setPlaceholderText("全部创建人")
        self.method = SchemeComboBox()
        self.method.addItem("全部报价方式", "")
        self.method.addItem("快速报价", "QUICK")
        self.method.addItem("公式法", "FORMULA")
        self.query_button = QPushButton("查询")
        self.query_button.setStyleSheet(button_style("primary"))
        self.query_button.clicked.connect(self.reload)
        self.reset_button = QPushButton("重置")
        self.reset_button.setStyleSheet(button_style("secondary"))
        self.reset_button.clicked.connect(self.reset)
        self.more_button = QPushButton("更多筛选")
        self.more_button.setObjectName("analysisLink")
        self.more_button.setCheckable(True)
        self.more_button.setToolTip("展开自定义开始日期、结束日期及报价方式")
        self.controls = [self.period,self.date_from,self.date_to,self.customer,self.product,self.status,self.creator,self.method,self.reset_button]
        self.filter_fields = [self.field(caption,editor) for caption,editor in
            [("时间范围",self.period),("客户",self.customer),("产品",self.product),("方案状态",self.status),("创建人",self.creator)]]
        self.filter_actions = QWidget()
        actions = QHBoxLayout(self.filter_actions)
        actions.setContentsMargins(0,0,0,0)
        actions.setSpacing(7)
        actions.addWidget(self.query_button)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.more_button)
        self.extra_filters = QWidget()
        extra = QHBoxLayout(self.extra_filters)
        extra.setContentsMargins(0,0,0,0)
        for caption,editor in [("开始日期",self.date_from),("结束日期",self.date_to),("折扣分析报价方式",self.method)]:
            extra.addWidget(self.field(caption,editor),1)
        self.extra_filters.hide()
        filter_column.addWidget(self.extra_filters)
        self.more_button.toggled.connect(self.extra_filters.setVisible)
        self.more_button.toggled.connect(lambda opened:self.more_button.setText("收起筛选" if opened else "更多筛选"))
        content_column.addWidget(self.filter_card)
        self.period.currentIndexChanged.connect(self.change_period)
        self.views = QStackedWidget()
        self.views.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Minimum)
        self.overview = QWidget()
        self.discounts = QWidget()
        self.views.addWidget(self.overview)
        self.views.addWidget(self.discounts)
        self.tabs.currentChanged.connect(self.views.setCurrentIndex)
        self.tabs.currentChanged.connect(lambda:self.position_content())
        content_column.addWidget(self.views)
        content_column.addStretch(1)
        outer.addWidget(self.scroll(self.content),1)
        self.build_overview()
        self.build_discounts()
        self.position_content()
        self.customer.currentIndexChanged.connect(self.dimension_changed)
        self.product.currentIndexChanged.connect(self.dimension_changed)
        main_scroll = window.findChild(QScrollArea,"mainScroll")
        if main_scroll is not None:
            main_scroll.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        # Window clamping and DPI changes may resize the viewport after the
        # legacy window resize callback. Fit this route to the settled area.
        if event.type()==QEvent.Type.Resize and self.window.stack.currentWidget() is self:
            QTimer.singleShot(0,self.window._scheme2_responsive_callback)
        return super().eventFilter(watched,event)

    @staticmethod
    def field(caption,editor):
        field=QWidget()
        column=QVBoxLayout(field)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(5)
        title=label(caption,"analysisFieldLabel")
        title.setBuddy(editor)
        column.addWidget(title)
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        editor.setFixedHeight(METRICS["field_height"])
        column.addWidget(editor)
        return field

    @staticmethod
    def style_sheet():
        return f"""
QWidget#quoteAnalysisPage {{ background:{COLORS['bg']}; font-family:{FONT_FAMILY_QSS}; color:{COLORS['text']}; }}
QWidget#quoteAnalysisPage QWidget {{ font-size:13px; }}
QWidget#quoteAnalysisPage QLabel {{ font-size:12px; background:transparent; color:{COLORS['secondary']}; }}
QWidget#quoteAnalysisPage QLabel#analysisTitle {{ font-size:20px; color:{COLORS['deep']}; font-weight:600; }}
QWidget#quoteAnalysisPage QLabel#analysisSubtitle {{ font-size:12px; color:{COLORS['muted']}; }}
QWidget#quoteAnalysisPage QLabel#analysisNotice {{ color:{COLORS['secondary']}; padding:8px 11px; background:#edf3fa; border-left:3px solid #8aadd5; }}
QWidget#quoteAnalysisPage QLabel#analysisFieldLabel {{ color:#49617e; }}
QWidget#quoteAnalysisPage QLabel#analysisSectionTitle {{ font-size:15px; color:{COLORS['deep']}; font-weight:600; }}
QWidget#quoteAnalysisPage QLabel#analysisObservation {{ padding:9px 11px; background:#edf3fa; border-left:3px solid #8aadd5; }}
QWidget#quoteAnalysisPage QFrame#analysisCard {{ background:white; border:1px solid {COLORS['border']}; border-radius:6px; }}
/* Override the scaled global minimum. QSS content height excludes the two
   one-pixel borders; keep the complete analytics field at field_height. */
QWidget#quoteAnalysisPage QLineEdit, QWidget#quoteAnalysisPage QComboBox, QWidget#quoteAnalysisPage QDateEdit {{ min-height:{METRICS['field_height']-2}px; max-height:{METRICS['field_height']-2}px; background:white; border:1px solid #c5d2df; border-radius:5px; padding:0 10px; font-size:13px; color:{COLORS['text']}; }}
QWidget#quoteAnalysisPage QComboBox::drop-down {{ border:0; width:22px; }}
QWidget#quoteAnalysisPage QComboBox::down-arrow {{ image:none; width:0; height:0; }}
QWidget#quoteAnalysisPage QComboBox {{ padding-right:24px; }}
QWidget#quoteAnalysisPage QComboBox QAbstractItemView {{ background:white; color:{COLORS['text']}; selection-background-color:#eaf1f8; font-size:13px; }}
QWidget#quoteAnalysisPage QTabBar::tab {{ padding:10px 2px; margin-right:22px; color:{COLORS['secondary']}; background:transparent; border-bottom:3px solid transparent; font-size:14px; }}
QWidget#quoteAnalysisPage QTabBar::tab:selected {{ color:{COLORS['deep']}; border-bottom-color:{COLORS['brand']}; font-weight:600; }}
QWidget#quoteAnalysisPage QScrollArea {{ background:transparent; border:0; }}
QWidget#quoteAnalysisPage QScrollArea > QWidget > QWidget {{ background:{COLORS['bg']}; }}
QWidget#quoteAnalysisPage QTableWidget {{ background:white; alternate-background-color:#f8fbff; color:{COLORS['deep']}; border:1px solid {COLORS['soft']}; font-size:12px; selection-background-color:#edf5ff; selection-color:{COLORS['deep']}; }}
QWidget#quoteAnalysisPage QTableWidget::item {{ padding:0 9px; border-bottom:1px solid {COLORS['soft']}; }}
QWidget#quoteAnalysisPage QHeaderView::section {{ background:{COLORS['head']}; color:{COLORS['deep']}; padding:9px; border:0; font-size:12px; font-weight:600; }}
QWidget#quoteAnalysisPage QPushButton#analysisLink {{ border:0; background:transparent; color:#185fa5; font-size:12px; padding:4px; }}
QWidget#quoteAnalysisPage QPushButton#analysisLink:hover {{ color:{COLORS['brand']}; }}
QWidget#quoteAnalysisPage QPushButton#analysisKpi {{ min-height:96px; max-height:96px; padding:0; }}
QWidget#quoteAnalysisPage QPushButton#analysisKpi[compact="true"] {{ min-height:86px; max-height:86px; }}
QWidget#quoteAnalysisPage QProgressBar {{ border:0; background:#e7eef5; border-radius:4px; min-height:7px; max-height:7px; }}
QWidget#quoteAnalysisPage QProgressBar::chunk {{ background:{COLORS['brand']}; border-radius:4px; }}
"""

    @staticmethod
    def scroll(widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    @staticmethod
    def card(title, note=""):
        card=QFrame()
        card.setObjectName("analysisCard")
        card.setMinimumWidth(0)
        column=QVBoxLayout(card)
        column.setContentsMargins(12,12,12,12)
        column.setSpacing(9)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        header=QWidget()
        header.setFixedHeight(24)
        head=QHBoxLayout(header)
        head.setContentsMargins(0,0,0,0)
        title_label=label(title,"analysisSectionTitle")
        title_label.setWordWrap(False)
        head.addWidget(title_label)
        head.addStretch(1)
        if note:
            note_label=label(note)
            note_label.setWordWrap(False)
            head.addWidget(note_label)
        column.addWidget(header)
        return card,column

    def build_overview(self):
        column = QVBoxLayout(self.overview)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(10)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.basis = label("统计口径：已报价方案按正式报价时间，草稿按创建时间。金额读取正式报价快照，不随当前价格变化。")
        column.addWidget(self.basis)
        self.kpi_layout = QGridLayout()
        self.kpi_layout.setSpacing(10)
        self.kpis = {}
        for key,caption,note in [("schemes","本期方案数","点击查看方案明细"),("quoted","已报价","正式报价快照"),("drafts","草稿","按创建时间统计"),("amount","报价总金额","正式报价金额合计"),
                            ("average","平均报价额","按金额完整方案计算"),("active_customers","活跃客户","客户归属明确的正式报价"),("failures","异常 / 失败","已记录的导出失败")]:
            button = KpiCard(caption,note)
            button.clicked.connect(lambda _=False,k=key:self.show_details(k))
            self.kpis[key] = (button,caption)
        column.addLayout(self.kpi_layout)
        self.dashboard_grid=QGridLayout()
        self.dashboard_grid.setSpacing(10)
        self.dashboard_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        column.addLayout(self.dashboard_grid)
        self.trend_card,trend_column=self.card("方案与报价趋势","● 新建方案   ● 已报价")
        legend=trend_column.itemAt(0).widget().findChildren(QLabel)[-1]
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setText('<span style="color:#2563eb">●</span> 新建方案　<span style="color:#79a943">●</span> 已报价')
        self.chart = TrendChart()
        self.chart.selected.connect(lambda date:self.show_details("date",date))
        trend_column.addWidget(self.chart)
        self.ranking_card,rank_column=self.card("客户 Top 5","按正式报价金额")
        self.ranking = CustomerRankChart()
        self.ranking.selected.connect(self.pick_customer)
        rank_column.addWidget(self.ranking)
        self.cost_card,cost_column=self.card("成本结构","公式法快照")
        self.costs = CostDonut()
        self.costs.selected.connect(self.show_cost_details)
        cost_column.addWidget(self.costs)
        self.coverage = label()
        self.coverage.setToolTip("只汇总完整的历史成本快照；缺失金额不按 0 元补齐。")
        cost_column.addWidget(self.coverage)
        self.recent_card,recent_column=self.card("最近报价方案","复用报价方案的打开流程")
        self.recent = table(["方案编号","客户","产品","状态","报价金额","创建人","最后修改人","更新时间","操作"],"analysisRecent")
        self.recent.horizontalHeader().setMinimumSectionSize(80)
        self.recent.setColumnWidth(0,165)
        self.recent.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        for col in (1,4,7):self.recent.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        self.recent.horizontalHeader().setMaximumSectionSize(250)
        self.recent.cellDoubleClicked.connect(self.open_recent)
        recent_column.addWidget(self.recent)
        self.events_card,events_column=self.card("异常与待办")
        self.events = label()
        self.events.setAlignment(Qt.AlignmentFlag.AlignTop)
        events_column.addWidget(self.events)
        events_column.addStretch(1)

    def build_discounts(self):
        column=QVBoxLayout(self.discounts)
        column.setContentsMargins(0,0,0,0)
        self.discount_card,panel=self.card("产品折扣与成交率")
        column.addWidget(self.discount_card)
        panel.addWidget(label("按客户与产品分别比较折扣系数和成交表现；同一产品在不同客户下独立统计。"))
        panel.addWidget(label("统计口径：按成交结果时间筛选，每个“客户 + 产品”分别统计。全部客户仅供汇总观察，不替代单一客户结论。"))
        toolbar=QHBoxLayout()
        self.discount_customer=SchemeComboBox()
        self.discount_product=SchemeComboBox()
        for caption,editor in [("选择客户",self.discount_customer),("选择产品",self.discount_product)]:
            field=self.field(caption,editor)
            field.setMaximumWidth(230)
            toolbar.addWidget(field,1)
        self.controls.extend([self.discount_customer,self.discount_product])
        self.discount_scope = label("请选择客户与产品查看折扣区间。")
        toolbar.addWidget(self.discount_scope,2)
        panel.addLayout(toolbar)
        self.discount_customer.currentIndexChanged.connect(lambda:self.local_dimension_changed(self.discount_customer,self.customer))
        self.discount_product.currentIndexChanged.connect(lambda:self.local_dimension_changed(self.discount_product,self.product))
        self.observation = label("全部客户为汇总观察，不能套作某一客户的折扣结论。","analysisObservation")
        panel.addWidget(self.observation)
        summary=QHBoxLayout()
        summary.setSpacing(10)
        self.best=label()
        self.best.hide()
        self.best_metric=KpiCard("历史成交率最高的折扣区间","有效样本至少 20 条",True)
        self.rate_metric=KpiCard("该区间成交率","成交产品行 ÷ 已决产品行",True)
        self.sample_metric=KpiCard("该区间有效样本","展示成交数与未成交数",True)
        for metric,stretch in [(self.best_metric,3),(self.rate_metric,2),(self.sample_metric,2)]:
            metric.setEnabled(False)
            summary.addWidget(metric,stretch)
        panel.addLayout(summary)
        self.bands = table(["报价折扣系数","成交","未成交","有效样本","成交率","提示"],"analysisBands")
        for index,width in ((0,190),(1,80),(2,80),(3,100),(5,130)):
            self.bands.horizontalHeader().setSectionResizeMode(index,QHeaderView.ResizeMode.Fixed)
            self.bands.setColumnWidth(index,width)
        self.bands.horizontalHeader().setStretchLastSection(False)
        self.bands.cellDoubleClicked.connect(self.show_outcome_details)
        panel.addWidget(self.bands)
        panel.addWidget(label("折扣沿用正式报价实际系数；运费与不参与折扣的附件不反算折扣。区间样本达到20条才参与最高区间比较；未决、作废及客户待确认记录不计入成交率。样本不足或无记录时不沿用其他客户结论。历史观察不会自动修改报价折扣。"))
        panel.addWidget(label("同一产品 · 各客户对比","analysisSectionTitle"))
        panel.addWidget(label("双击客户查看该客户的折扣区间，不混合客户样本。"))
        self.customer_comparison = table(["客户","历史最高成交率区间","成交率","该区间有效样本","本产品已决总样本"],"analysisCustomerComparison")
        self.customer_comparison.cellDoubleClicked.connect(self.pick_discount_customer)
        panel.addWidget(self.customer_comparison)
        panel.addWidget(label("当前客户 · 各产品表现","analysisSectionTitle"))
        panel.addWidget(label("双击产品查看，保留所选客户。"))
        self.product_comparison = table(["产品","最高成交率所在区间","成交率","该区间有效样本","已决总样本"],"analysisProductComparison")
        self.product_comparison.cellDoubleClicked.connect(self.pick_discount_product)
        panel.addWidget(self.product_comparison)

    def local_dimension_changed(self,source,target):
        if self._populate:return
        code=source.currentData()
        index=target.findData(code)
        if index>=0:target.setCurrentIndex(index)

    def position_content(self):
        if not hasattr(self,'kpis'):return
        width=self.window.width()
        columns=7 if width>=1500 else 4 if width>=1000 else 2
        while self.kpi_layout.count():self.kpi_layout.takeAt(0)
        for i,(button,_) in enumerate(self.kpis.values()):
            self.kpi_layout.addWidget(button,i//columns,i%columns)
        for i in range(7):self.kpi_layout.setColumnStretch(i,1 if i<columns else 0)
        while self.filter_layout.count():self.filter_layout.takeAt(0)
        filter_columns=5 if width>=1500 else 3 if width>=1100 else 2
        for i,field in enumerate(self.filter_fields):
            self.filter_layout.addWidget(field,i//filter_columns,i%filter_columns)
        if filter_columns==5:self.filter_layout.addWidget(self.filter_actions,0,5,Qt.AlignmentFlag.AlignBottom)
        else:self.filter_layout.addWidget(self.filter_actions,4//filter_columns,filter_columns-1,Qt.AlignmentFlag.AlignBottom)
        for i in range(6):self.filter_layout.setColumnStretch(i,1 if i<filter_columns else 0)
        while self.dashboard_grid.count():self.dashboard_grid.takeAt(0)
        if width>=1500:
            positions=[(self.trend_card,0,0,1,1),(self.ranking_card,0,1,1,1),(self.cost_card,0,2,1,1),(self.recent_card,1,0,1,2),(self.events_card,1,2,1,1)]
            stretches=(165,100,100)
        elif width>=1100:
            positions=[(self.trend_card,0,0,1,1),(self.ranking_card,0,1,1,1),(self.cost_card,1,0,1,1),(self.events_card,1,1,1,1),(self.recent_card,2,0,1,2)]
            stretches=(150,100,0)
        else:
            positions=[(widget,i,0,1,1) for i,widget in enumerate((self.trend_card,self.ranking_card,self.cost_card,self.recent_card,self.events_card))]
            stretches=(1,0,0)
        for widget,r,c,rs,cs in positions:self.dashboard_grid.addWidget(widget,r,c,rs,cs)
        for i,stretch in enumerate(stretches):self.dashboard_grid.setColumnStretch(i,stretch)
        for widget in (self.overview,self.discounts):
            widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred if widget is self.views.currentWidget() else QSizePolicy.Policy.Ignored)
        self.views.currentWidget().layout().activate()
        self.views.setFixedHeight(self.views.currentWidget().sizeHint().height())

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.position_content()

    def change_period(self):
        today = QDate.currentDate()
        index = self.period.currentIndex()
        start = today.addDays(1-today.day()) if index==0 else today.addDays(1-today.dayOfWeek()) if index==1 else today.addDays(-29)
        self.date_from.setDate(start)
        self.date_to.setDate(today)
        self.date_from.setEnabled(index!=3)
        self.date_to.setEnabled(index!=3)

    def filters(self):
        result = {"customer":str(self.customer.currentData() or ""),"product":str(self.product.currentData() or ""),
                  "creator":self.creator.text().strip(),"status":str(self.status.currentData() or ""),
                  "method":str(self.method.currentData() or "")}
        if self.period.currentIndex()!=3:
            result.update({"from":self.date_from.date().toString("yyyy-MM-dd"),"to":self.date_to.date().toString("yyyy-MM-dd")})
        return result

    def reset(self):
        self._populate = True
        for combo in (self.customer,self.product,self.status,self.method,self.period):
            combo.setCurrentIndex(0)
        self.creator.clear()
        self._populate = False
        self.change_period()
        self.reload()

    def dimension_changed(self):
        if self.data is not None and not self._populate:
            self.reload()

    def set_busy(self,busy):
        self.query_button.setEnabled(not busy)
        self.query_button.setText("加载中…" if busy else "查询")
        for control in self.controls:
            control.setEnabled(not busy)
        if not busy and self.period.currentIndex()==3:
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        self.record_button.setEnabled(not busy and bool(self.data and self.data.get("outcomes_available")))

    def request(self,path,payload=None,success=None):
        if self.worker is not None:
            return False
        worker = AnalysisWorker(self.window,path,payload)
        self.worker = worker
        self.set_busy(True)
        worker.succeeded.connect(success or self.loaded)
        worker.failed.connect(self.failed)
        def finished():
            self.worker = None
            worker.deleteLater()
            self.set_busy(False)
            if self.pending_reload:
                self.pending_reload = False
                QTimer.singleShot(0,self.reload)
        worker.finished.connect(finished)
        worker.start()
        return True

    def reload(self):
        if self.worker is not None:
            self.pending_reload = True
            return
        params = self.filters()
        if params.get("from","") > params.get("to","9999"):
            self.notice.setText("开始日期不能晚于结束日期。")
            return
        # Do not leave old customer numbers visible while another scope loads.
        self.clear_results()
        self.notice.setText("正在读取服务器报价快照…")
        self.request("/api/quote-analysis?"+urllib.parse.urlencode(params))

    def clear_results(self):
        for widget in (self.recent,self.bands,self.customer_comparison,self.product_comparison):
            widget.setRowCount(0)
        for button,caption in self.kpis.values():
            button.setText(caption+"\n—")
        self.chart.set_rows([])
        self.discount_scope.setText("尚未取得当前条件的数据。")
        self.ranking.set_rows([])
        self.costs.set_rows({})
        for metric,caption in ((self.best_metric,"历史成交率最高的折扣区间"),(self.rate_metric,"该区间成交率"),(self.sample_metric,"该区间有效样本")):
            metric.setText(caption+"\n—")
        self.best.clear()
        self.observation.clear()
        self.coverage.clear()
        self.events.clear()
        self.data = None
        self.record_button.setEnabled(False)

    def failed(self,message):
        self.clear_results()
        self.notice.setText(str(message)+" 点击“查询”重新加载。")
        self.discount_scope.setText("本次未取得有效数据，未显示缓存统计。")

    def loaded(self,result):
        if not isinstance(result,dict) or not isinstance(result.get("summary"),dict):
            self.failed("服务端返回的分析数据不完整。")
            return
        self.data = result
        self._populate = True
        for combo,key,all_text in ((self.customer,"customers","全部客户（汇总观察）"),(self.product,"products","全部产品")):
            selected = combo.currentData()
            combo.clear()
            combo.addItem(all_text,"")
            for item in result.get(key,[]):
                combo.addItem(str(item["name"]),str(item["code"]))
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0,index))
        for source,target in ((self.customer,self.discount_customer),(self.product,self.discount_product)):
            target.clear()
            for i in range(source.count()):target.addItem(source.itemText(i),source.itemData(i))
            target.setCurrentIndex(source.currentIndex())
        self._populate = False
        summary = result["summary"]
        for key,(button,caption) in self.kpis.items():
            button.setText(caption+"\n"+number(summary.get(key),key in ("amount","average")))
        self.chart.set_rows(result.get("trend",[]))
        self.ranking.set_rows(result.get("ranking",[]))
        self.costs.set_rows(result.get("costs",{}))
        self.coverage.setText(f"金额覆盖 {summary.get('amount_coverage',0)}/{summary.get('quoted',0)} 个方案 · 完整成本 {result.get('cost_coverage',0)} 行")
        fill(self.recent,[self.scheme_values(s) for s in result.get("recent",[])])
        for row in range(self.recent.rowCount()):
            open_button = QPushButton("打开")
            open_button.setObjectName("analysisLink")
            open_button.clicked.connect(lambda _=False,r=row:self.open_recent(r))
            self.recent.setCellWidget(row,8,open_button)
        self.events.setText("\n\n".join(f"导出失败 · {r['scheme_no']}\n{r['date']} · {r['kind']}" for r in result.get("failures",[])) if result.get("failures") else "当前条件下暂无已记录的导出失败。\n\n计算与网络事件尚未接入统一数据源。")
        self.render_discount(result)
        self.notice.setText("已从报价服务器加载。" if result.get("details") else "当前条件下暂无报价方案，可清除筛选后重试。")
        if not result.get("outcomes_available"):
            self.notice.setText(self.notice.text()+" 成交结果功能尚未启用，需要管理员执行新增迁移。")
        self.record_button.setEnabled(bool(result.get("outcomes_available")))
        self.position_content()

    @staticmethod
    def scheme_values(s):
        return (s["scheme_no"],s.get("customer_name") or "客户待确认","；".join(dict.fromkeys(p.get("product_name") or p.get("product_code","") for p in s.get("products",[]))),
                schemes.STATUS_TEXT.get(s["status"],s["status"]),number(s.get("analysis_amount",s.get("amount")),True),s.get("creator",""),s.get("last_editor",""),s.get("updated_at",""),"")

    def render_discount(self,result):
        d = result.get("discount",{})
        customer = self.customer.currentText()
        product = d.get("product_code","")
        self.discount_scope.setText(f"当前查看：{customer} · {product or '暂无产品'} · 已决样本 {d.get('sample',0)} 条。按结果日期统计。")
        self._populate=True
        self.discount_product.setCurrentIndex(max(0,self.discount_product.findData(product)))
        self._populate=False
        self.observation.setText("全部客户为汇总观察，不能套作某一客户的折扣结论。" if not self.customer.currentData() else "当前客户与产品独立统计，不套用其他客户的折扣结论。")
        best = d.get("best",[])
        if not result.get("outcomes_available"):
            self.best.setText("尚无成交结果数据：请先由管理员启用成交登记功能。")
        elif not d.get("sample"):
            self.best.setText("该客户与产品暂无已登记的成交或未成交记录。")
        elif not best:
            self.best.setText("样本不足或折扣待确认，不给出最高区间。")
        else:
            self.best.setText("历史最高成交率区间："+"；".join(f"{b['label']} · {b['rate']}% · {b['sample']}条" for b in best))
        if not best:
            self.observation.setText(self.best.text()+" "+self.observation.text())
        contextual=bool(self.customer.currentData()) and bool(best)
        self.observation.setStyleSheet("background:#f0f7e9; color:#3b6d11; border-left:3px solid #79a943; padding:9px 11px;" if contextual else
                                      "background:#fff2d8; color:#955b0a; border-left:3px solid #d89a32; padding:9px 11px;" if not best else "")
        best_value="；".join(b['label'] for b in best) or "—"
        self.best_metric.setText(("该客户与产品的历史最高成交率区间" if self.customer.currentData() else "历史成交率最高的折扣区间")+"\n"+best_value)
        self.rate_metric.setText("该区间成交率\n"+("；".join(f"{b['rate']}%" for b in best) or "—"))
        self.sample_metric.setText("该区间有效样本\n"+("；".join(f"{b['sample']} 条" for b in best) or "—"))
        self.best_metric.note="；".join(f"成交 {b['won']} 条 · 未成交 {b['lost']} 条" for b in best) or self.best.text()
        self.best_metric.setToolTip(self.best.text())
        self.best_metric.update()
        fill(self.bands,[(b["label"],b["won"],b["lost"],b["sample"],"—" if b["rate"] is None else f"{b['rate']}%",
                          "最高区间" if b in best else "样本不足" if b["sample"]<20 else "仅观察") for b in d.get("bands",[])])
        for row,b in enumerate(d.get('bands',[])):
            for col in (1,2,3):
                self.bands.item(row,col).setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                self.bands.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            cell=QWidget()
            line=QHBoxLayout(cell);line.setContentsMargins(9,0,9,0);line.setSpacing(8)
            bar=QProgressBar();bar.setRange(0,1000);bar.setTextVisible(False)
            bar.setValue(round(float(b['rate'] or 0)*10))
            if b in best:bar.setStyleSheet('QProgressBar::chunk {background:#6b9e35;}')
            line.addWidget(bar,1)
            line.addWidget(label('—' if b['rate'] is None else f"{b['rate']}%"))
            self.bands.setCellWidget(row,4,cell)
            self.bands.item(row,4).setText("")
            if b in best:
                for col in range(self.bands.columnCount()):
                    self.bands.item(row,col).setBackground(QColor('#f0f7e9'))
                cell.setStyleSheet('background:#f0f7e9;')
        def compare(rows):
            return [(r["name"],"；".join(b["label"] for b in r["best"]) or ("样本不足" if r["sample"] else "暂无记录"),
                     "；".join(f"{b['rate']}%" for b in r["best"]) or "—","；".join(str(b["sample"]) for b in r["best"]) or "—",r["sample"]) for r in rows]
        fill(self.customer_comparison,compare(d.get("customer_comparison",[])))
        fill(self.product_comparison,compare(d.get("product_comparison",[])))

    def pick_customer(self,row,col=0):
        if self.data and row<len(self.data.get("ranking",[])):
            self.customer.setCurrentIndex(max(0,self.customer.findData(self.data["ranking"][row]["customer_code"])))

    def pick_discount_customer(self,row,col=0):
        if not self.data:
            return
        record = self.data["discount"]["customer_comparison"][row]
        # Preserve the displayed product when the top selector was 'all'.
        self._populate = True
        self.product.setCurrentIndex(max(0,self.product.findData(self.data["discount"]["product_code"])))
        self.customer.setCurrentIndex(max(0,self.customer.findData(record["customer_code"])))
        self._populate = False
        self.reload()

    def pick_discount_product(self,row,col=0):
        if self.data:
            code = self.data["discount"]["product_comparison"][row]["product_code"]
            self.product.setCurrentIndex(max(0,self.product.findData(code)))

    def open_recent(self,row,col=0):
        if self.data and row<len(self.data.get("recent",[])):
            schemes._open_scheme(self.window,self.data["recent"][row]["scheme_no"])

    def show_details(self,key,value=None):
        if not self.data:
            return
        rows = self.data.get("details",[])
        if key in ("quoted","amount","average","active_customers"):
            rows = [s for s in rows if s.get("formal_date") and s["status"]!="VOID"]
        elif key=="drafts":
            rows = [s for s in rows if s["status"]=="DRAFT"]
        elif key=="date":
            rows = [s for s in self.data.get("trend_details",rows) if s.get("formal_date")==value or s.get("created_date")==value]
        elif key=="failures":
            events = self.data.get("failures",[])
            self.detail_dialog("已记录的导出失败",["方案编号","日期","类型"],
                               [(e["scheme_no"],e["date"],e["kind"]) for e in events],events)
            return
        self.detail_dialog("报价统计明细",["方案编号","客户","产品","状态","报价金额","创建人","最后修改人","更新时间"],
                           [self.scheme_values(s)[:8] for s in rows],rows)

    def show_cost_details(self):
        if self.data is not None:
            self.detail_dialog("成本结构明细（完整公式法快照）",["成本项","合计"],
                               [(COST_NAMES.get(key,key),number(value,True)) for key,value in self.data.get('costs',{}).items()])

    def detail_dialog(self,title,headers,rows,schemes_rows=None):
        dialog = QDialog(self.window)
        dialog.setWindowTitle(title)
        dialog.resize(min(980,max(600,self.window.width()-80)),min(620,max(360,self.window.height()-80)))
        column = QVBoxLayout(dialog)
        grid = table(headers,"analysisDetailTable")
        fill(grid,rows)
        column.addWidget(grid)
        if schemes_rows is not None:
            def open_row(row,col):
                dialog.close()
                schemes._open_scheme(self.window,schemes_rows[row]["scheme_no"])
            grid.cellDoubleClicked.connect(open_row)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.close)
        column.addWidget(close)
        style_dialog(dialog)
        self._detail_dialog = dialog
        dialog.show()

    def show_outcome_details(self,row,col=0):
        if not self.data:
            return
        d = self.data["discount"]
        band = d["bands"][row]
        records = []
        for record in d.get("records",[]):
            discount = record.get("discount")
            key = "unknown" if discount is None else next((b["key"] for b in d["bands"] if b["key"] not in ("outside","unknown") and
                float(b["label"].split("–")[0])<=float(discount) and (float(discount)<float(b["label"].split("–")[-1].lstrip("<")) or ("<" not in b["label"] and float(discount)==1))),"outside")
            if key==band["key"]:
                records.append(record)
        self.detail_dialog("成交结果明细 · "+band["label"],["方案","正式版本","客户编码","商机/订单编号","产品","结果","结果日期","折扣系数"],
                           [(r["scheme_no"],r["version_no"],r["customer_code"],r["opportunity_key"],r["product_code"],"成交" if r["result"]=="WON" else "未成交",r["result_date"],r["discount"]) for r in records])

    def record_dialog(self):
        if not self.data or not self.data.get("outcomes_available") or self.worker is not None:
            return
        choices = [s for s in self.data.get("details",[]) if s.get("can_record") and s.get("formal_version") and s.get("customer_code") and s["status"]!="VOID"]
        if not choices:
            QMessageBox.information(self.window,"登记成交结果","当前条件下没有客户归属明确的正式报价，请先查询已导出方案。")
            return
        dialog = QDialog(self.window)
        dialog.setWindowTitle("登记成交结果")
        dialog.resize(METRICS["dialog_width"],470)
        outer = QVBoxLayout(dialog)
        outer.addWidget(label("登记独立成交结果，不修改原方案、报价或折扣。同一商机/订单请使用相同编号，重复登记会校验版本并保留审计记录。"))
        form = QFormLayout()
        scheme = SchemeComboBox()
        for s in choices:
            scheme.addItem(s["scheme_no"]+" · "+s["customer_name"]+" · V"+str(s["formal_version"]),s)
        product = SchemeComboBox()
        def change_product():
            product.clear()
            for p in scheme.currentData()["products"]:
                code = p.get("product_code")
                if code and product.findData(code)<0:
                    product.addItem(p.get("product_name") or code,code)
        scheme.currentIndexChanged.connect(change_product)
        change_product()
        opportunity = QLineEdit()
        opportunity.setMaxLength(200)
        opportunity.setPlaceholderText("必须填写；同一业务跨版本/复制方案使用相同编号")
        result = SchemeComboBox()
        for caption,code in (("成交","WON"),("未成交","LOST"),("待定（撤回已决结果）","PENDING")):
            result.addItem(caption,code)
        result_date = QDateEdit(QDate.currentDate())
        result_date.setCalendarPopup(True)
        result_date.setDisplayFormat("yyyy-MM-dd")
        actor = QLineEdit(schemes._operator_name(self.window))
        actor.setMaxLength(100)
        for caption,widget in (("正式报价",scheme),("产品",product),("商机/订单编号",opportunity),("成交结果",result),("结果日期",result_date),("操作人",actor)):
            form.addRow(caption,widget)
        outer.addLayout(form)
        error = label()
        outer.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            if not opportunity.text().strip() or not actor.text().strip() or not product.currentData():
                error.setText("请填写商机/订单编号、操作人并选择产品。")
                return
            s = scheme.currentData()
            prior = next((r for r in self.data.get("outcome_records",[]) if r["customer_code"]==s["customer_code"] and r["product_code"]==product.currentData() and r["opportunity_key"]==opportunity.text().strip()),None)
            if prior and QMessageBox.question(dialog,"确认修正结果","同一客户、商机与产品已有结果。是否修正并保留审计记录？")!=QMessageBox.StandardButton.Yes:
                return
            payload = {"scheme_no":s["scheme_no"],"version_no":s["formal_version"],"product_code":product.currentData(),
                       "customer_code":s["customer_code"],"opportunity_key":opportunity.text().strip(),
                       "result":result.currentData(),"result_date":result_date.date().toString("yyyy-MM-dd"),
                       "operator_name":actor.text().strip(),"expected_revision":prior["revision"] if prior else 0}
            def recorded(response):
                if response.get("recorded") is True:
                    self.notice.setText("成交结果已登记，正在刷新分析。")
                    self.pending_reload = True
                else:
                    self.failed("服务端未确认成交结果保存。")
            if self.request("/api/quote-analysis/outcomes",payload,recorded):
                dialog.accept()
        buttons.accepted.connect(save)
        outer.addWidget(buttons)
        style_dialog(dialog)
        self._record_dialog = dialog
        dialog.show()


def install_quote_analysis(namespace):
    cls = namespace["MainWindow"]
    if getattr(cls,"_quote_analysis_installed",False):
        return
    cls._quote_analysis_installed = True
    prior_init,prior_section,prior_close = cls.__init__,cls.show_section,cls.closeEvent
    def init(window,*args,**kwargs):
        prior_init(window,*args,**kwargs)
        window.quote_analysis_page = AnalysisPage(window)
        window.quote_analysis_route = window.stack.addWidget(window.quote_analysis_page)
        button = QPushButton("报价分析")
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setFixedHeight(window.nav_buttons[0].height())
        button.clicked.connect(lambda:window.show_section(window.quote_analysis_route))
        window.scheme2_nav.layout().insertWidget(window.scheme2_nav.layout().indexOf(window.quote_scheme_nav_button)+1,button)
        window.quote_analysis_nav_button = button
        window.nav_buttons.append(button)
        window.nav_routes = (*window.nav_routes,(window.quote_analysis_route,"报价分析","",None))
    def section(window,index):
        if hasattr(window,"quote_analysis_route") and index==window.quote_analysis_route:
            window.stack.setCurrentIndex(index)
            for button in window.nav_buttons:
                button.setChecked(button is window.quote_analysis_nav_button)
            from scheme2_ui import _apply_responsive
            _apply_responsive(window)
            QTimer.singleShot(0,lambda:_apply_responsive(window))
            window.quote_analysis_page.reload()
            return
        result = prior_section(window,index)
        if hasattr(window,"quote_analysis_nav_button"):
            window.quote_analysis_nav_button.setChecked(False)
        return result
    def close(window,event):
        page = window.quote_analysis_page
        if page.worker is not None:
            page.notice.setText("请等待当前分析查询或成交登记完成后再关闭。")
            event.ignore()
            return
        return prior_close(window,event)
    cls.__init__,cls.show_section,cls.closeEvent = init,section,close
