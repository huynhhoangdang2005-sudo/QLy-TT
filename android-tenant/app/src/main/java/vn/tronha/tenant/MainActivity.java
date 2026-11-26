package vn.tronha.tenant;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.NumberFormat;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final int PICK_IMAGE = 7102;
    private static final int GREEN = Color.rgb(20, 92, 69);
    private static final int INK = Color.rgb(32, 53, 43);
    private static final int MUTED = Color.rgb(111, 128, 118);
    private static final int BG = Color.rgb(242, 246, 242);
    private static final int BORDER = Color.rgb(224, 234, 226);
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final NumberFormat currency = NumberFormat.getNumberInstance(new Locale("vi", "VN"));
    private android.content.SharedPreferences prefs;
    private String token = "";
    private String customerName = "";
    private String tab = "bills";
    private String activeUtility = "";
    private String electricDataUrl = "";
    private String waterDataUrl = "";
    private Bitmap selectedBitmap;
    private LinearLayout page;
    private LinearLayout content;
    private EditText serverInput;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText electricReading;
    private EditText waterReading;
    private Button electricSend;
    private Button waterSend;
    private ImageView electricPreview;
    private ImageView waterPreview;
    private TextView electricOcr;
    private TextView waterOcr;
    private TextView electricResult;
    private TextView waterResult;
    private boolean isLoading;

    private final Runnable refreshTask = new Runnable() {
        @Override public void run() {
            if (!token.isEmpty() && !isFinishing() && "bills".equals(tab)) loadHome(false);
            handler.postDelayed(this, 5000);
        }
    };

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("tenant", MODE_PRIVATE);
        token = prefs.getString("token", "");
        customerName = prefs.getString("name", "");
        if (token.isEmpty()) showLogin(); else showHome();
        handler.postDelayed(refreshTask, 5000);
    }

    @Override protected void onDestroy() {
        handler.removeCallbacks(refreshTask);
        executor.shutdownNow();
        super.onDestroy();
    }

    private void showLogin() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout root = column(); root.setPadding(dp(22), dp(24), dp(22), dp(24));
        root.setGravity(Gravity.CENTER_VERTICAL);
        scroll.addView(root);
        TextView brand = text("⌂  Trọ Nhà", 24, GREEN, true); root.addView(brand);
        TextView subtitle = text("Ứng dụng dành cho khách thuê", 14, MUTED, false); root.addView(subtitle, margin(0, 5, 0, 22));
        LinearLayout card = card(); card.setPadding(dp(20), dp(20), dp(20), dp(20)); root.addView(card, match());
        card.addView(text("Đăng nhập", 21, INK, true));
        card.addView(text("Nhập địa chỉ máy chủ do quản lý cung cấp, cùng số điện thoại và mật khẩu của bạn.", 13, MUTED, false), margin(0, 8, 0, 14));
        serverInput = field("Địa chỉ máy chủ, ví dụ http://192.168.1.5:8765", false);
        serverInput.setText(prefs.getString("server", "")); card.addView(serverInput, margin(0, 5, 0, 10));
        usernameInput = field("Số điện thoại / tên đăng nhập", false); card.addView(usernameInput, margin(0, 0, 0, 10));
        passwordInput = field("Mật khẩu", true); card.addView(passwordInput, margin(0, 0, 0, 14));
        Button login = primary("Đăng nhập"); card.addView(login, match());
        login.setOnClickListener(v -> login());
        TextView hint = text("Điện thoại cần kết nối cùng Wi‑Fi với máy tính quản lý.", 12, MUTED, false); root.addView(hint, margin(3, 14, 3, 0));
        setContentView(scroll);
    }

    private void login() {
        String base = serverInput.getText().toString().trim().replaceAll("/+$", "");
        String username = usernameInput.getText().toString().trim();
        String password = passwordInput.getText().toString();
        if (base.isEmpty() || username.isEmpty() || password.isEmpty()) { toast("Nhập địa chỉ máy chủ, tên đăng nhập và mật khẩu."); return; }
        if (!base.startsWith("http://") && !base.startsWith("https://")) base = "http://" + base;
        final String apiBase = base;
        setBusy(true);
        executor.execute(() -> {
            try {
                JSONObject response = request(apiBase, "/api/login", null,
                        new JSONObject().put("username", username).put("password", password));
                token = response.getString("token"); customerName = response.optString("name", "");
                prefs.edit().putString("server", apiBase).putString("token", token).putString("name", customerName).apply();
                runOnUiThread(() -> { setBusy(false); showHome(); });
            } catch (Exception e) { runOnUiThread(() -> { setBusy(false); toast(errorMessage(e)); }); }
        });
    }

    private void showHome() {
        ScrollView scroll = new ScrollView(this);
        page = column(); page.setBackgroundColor(BG); scroll.addView(page);
        LinearLayout header = row(); header.setGravity(Gravity.CENTER_VERTICAL); header.setPadding(dp(18), dp(16), dp(18), dp(12));
        LinearLayout brand = column(); brand.addView(text("Trọ Nhà", 20, INK, true));
        brand.addView(text("Khách thuê", 11, MUTED, false)); header.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        Button logout = button("Đăng xuất", false); header.addView(logout); logout.setOnClickListener(v -> logout());
        page.addView(header);
        LinearLayout welcome = column(); welcome.setPadding(dp(20), dp(8), dp(20), dp(16));
        welcome.addView(text("Xin chào" + (customerName.isEmpty() ? "" : ", " + customerName), 25, INK, true));
        welcome.addView(text("Hóa đơn và dịch vụ phòng trọ của bạn", 13, MUTED, false), margin(0, 4, 0, 0)); page.addView(welcome);
        LinearLayout nav = row(); nav.setPadding(dp(14), 0, dp(14), dp(12));
        Button bills = button("Hóa đơn", "bills".equals(tab)); Button meters = button("Điện / Nước", "meters".equals(tab)); Button notes = button("Thông báo", "notices".equals(tab));
        nav.addView(bills, new LinearLayout.LayoutParams(0, dp(44), 1)); nav.addView(meters, new LinearLayout.LayoutParams(0, dp(44), 1)); nav.addView(notes, new LinearLayout.LayoutParams(0, dp(44), 1));
        page.addView(nav);
        bills.setOnClickListener(v -> { tab="bills"; showHome(); loadHome(false); });
        meters.setOnClickListener(v -> { tab="meters"; showHome(); loadReadings(); });
        notes.setOnClickListener(v -> { tab="notices"; showHome(); loadNotifications(); });
        content = column(); content.setPadding(dp(16), dp(2), dp(16), dp(28)); page.addView(content);
        if ("bills".equals(tab)) loadHome(false);
        else if ("meters".equals(tab)) showMeterForms();
        else loadNotifications();
        setContentView(scroll);
    }

    private void showMeterForms() {
        content.removeAllViews();
        content.addView(meterCard("Điện", "kWh", true), margin(0, 0, 0, 14));
        content.addView(meterCard("Nước", "m³", false), margin(0, 0, 0, 14));
        TextView help = text("Chọn ảnh để tự đọc và gửi chỉ số. Nếu đọc sai, sửa số rồi bấm gửi lại. Hóa đơn đủ khi có cả điện và nước.", 12, MUTED, false); content.addView(help, margin(3, 0, 3, 12));
        loadReadings();
    }

    private LinearLayout meterCard(String utility, String unit, boolean electric) {
        LinearLayout box = card(); box.setPadding(dp(16), dp(16), dp(16), dp(16));
        box.addView(text((electric ? "⚡  " : "💧  ") + utility, 19, GREEN, true));
        box.addView(text("Chụp ảnh hoặc chọn ảnh công tơ trong thư viện.", 12, MUTED, false), margin(0, 4, 0, 10));
        ImageView preview = new ImageView(this); preview.setScaleType(ImageView.ScaleType.CENTER_CROP); preview.setVisibility(View.GONE);
        preview.setBackground(round(BG, 12));
        LinearLayout.LayoutParams previewParams = new LinearLayout.LayoutParams(-1, dp(170)); previewParams.bottomMargin=dp(9); box.addView(preview, previewParams);
        TextView ocr = text("", 12, GREEN, false); box.addView(ocr, margin(0, 0, 0, 6));
        Button choose = button("Chọn ảnh từ thư viện", false); box.addView(choose, match());
        EditText reading = field("Chỉ số hiện tại (" + unit + ")", false); reading.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL); box.addView(reading, margin(0, 10, 0, 8));
        TextView oldReading = text("Đang tải chỉ số gần nhất…", 11, MUTED, false); box.addView(oldReading, margin(0, 0, 0, 8));
        Button send = primary(electric ? "Gửi / sửa chỉ số điện" : "Gửi / sửa chỉ số nước"); box.addView(send, match());
        TextView result = text("", 12, GREEN, false); box.addView(result, margin(0, 8, 0, 0));
        choose.setOnClickListener(v -> { activeUtility=utility; activePreview=preview; activeOcr=ocr; activeReading=reading; activeResult=result; pickImage(); });
        send.setOnClickListener(v -> sendReading(utility, reading, result, send));
        if (electric) { electricReading=reading; electricPreview=preview; electricOcr=ocr; electricResult=result; electricSend=send; }
        else { waterReading=reading; waterPreview=preview; waterOcr=ocr; waterResult=result; waterSend=send; }
        return box;
    }

    private ImageView activePreview;
    private TextView activeOcr;
    private EditText activeReading;
    private TextView activeResult;

    private void pickImage() {
        Intent intent = new Intent(Intent.ACTION_GET_CONTENT); intent.setType("image/*"); intent.addCategory(Intent.CATEGORY_OPENABLE);
        startActivityForResult(Intent.createChooser(intent, "Chọn ảnh công tơ " + activeUtility.toLowerCase()), PICK_IMAGE);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK_IMAGE || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri=data.getData();
        final String utility=activeUtility;
        final ImageView targetPreview=activePreview;
        final TextView targetOcr=activeOcr;
        final EditText targetReading=activeReading;
        final Button targetSend="Điện".equals(utility)?electricSend:waterSend;
        try {
            InputImage image=InputImage.fromFilePath(this,uri);
            if (targetPreview != null) { targetPreview.setImageURI(uri); targetPreview.setVisibility(View.VISIBLE); }
            if (targetOcr != null) targetOcr.setText("Đang nhận dạng số trên ảnh…");
            TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS).process(image)
                    .addOnSuccessListener(text -> applyOcr(text,targetOcr,targetReading,utility,targetSend))
                    .addOnFailureListener(e -> { if(targetOcr!=null)targetOcr.setText("Chưa đọc được số tự động; vui lòng nhập số bên dưới."); });
            String imageData=compressImage(uri);
            if("Điện".equals(utility))electricDataUrl=imageData;else waterDataUrl=imageData;
        } catch (Exception e) { toast("Không mở được ảnh. Hãy chọn ảnh JPG hoặc PNG khác."); }
    }

    private void applyOcr(Text result,TextView targetOcr,EditText targetReading,String utility,Button targetSend) {
        if (targetOcr == null || targetReading == null) return;
        Matcher matcher=Pattern.compile("\\d+(?:[.,]\\d+)?").matcher(result.getText());
        String best="";
        while (matcher.find()) if (matcher.group().length()>best.length()) best=matcher.group();
        if (best.isEmpty()) targetOcr.setText("Không nhận dạng rõ chỉ số. Vui lòng nhập thủ công.");
        else {
            best=best.replace(',', '.'); targetReading.setText(best);
            targetOcr.setText("Đã đọc được " + best + "; đang tự gửi để tính hóa đơn. Nếu số sai, sửa bên dưới rồi gửi lại.");
            if(targetSend!=null)sendReading(utility,targetReading,"Điện".equals(utility)?electricResult:waterResult,targetSend);
        }
    }

    private String compressImage(Uri uri) throws Exception {
        Bitmap source;
        try (InputStream stream=getContentResolver().openInputStream(uri)) { source=BitmapFactory.decodeStream(stream); }
        if (source == null) throw new IllegalArgumentException("Ảnh không đọc được");
        int max=1800; float scale=Math.min(1f,(float)max/Math.max(source.getWidth(),source.getHeight()));
        Bitmap bitmap=scale<1f?Bitmap.createScaledBitmap(source,Math.round(source.getWidth()*scale),Math.round(source.getHeight()*scale),true):source;
        ByteArrayOutputStream out=new ByteArrayOutputStream();bitmap.compress(Bitmap.CompressFormat.JPEG,82,out);
        if(bitmap!=source)bitmap.recycle();source.recycle();
        return "data:image/jpeg;base64,"+android.util.Base64.encodeToString(out.toByteArray(),android.util.Base64.NO_WRAP);
    }

    private void sendReading(String utility, EditText readingField, TextView result, Button button) {
        String reading=readingField.getText().toString().trim();
        if(reading.isEmpty()){toast("Nhập chỉ số " + utility.toLowerCase() + " trước khi gửi.");return;}
        String image="Điện".equals(utility)?electricDataUrl:waterDataUrl;
        if(image.isEmpty()) { toast("Chọn ảnh công tơ " + utility.toLowerCase() + " trước khi gửi."); return; }
        String value=reading;
        button.setEnabled(false);result.setText("Đang cập nhật hóa đơn…");
        executor.execute(() -> {
            try {
                JSONObject body=new JSONObject().put("utility",utility).put("reading",value).put("ocr_reading",value).put("image",image);
                JSONObject response=request(apiBase(),"/api/readings",token,body);
                runOnUiThread(() -> {
                    boolean complete=response.optBoolean("complete",false);
                    String message=complete
                            ? "Đã cập nhật đủ điện nước. Hóa đơn tháng này: " + money(response.optDouble("invoice_total")) + "."
                            : "Đã ghi nhận " + utility.toLowerCase() + ". Hóa đơn tạm tính: " + money(response.optDouble("invoice_total")) + "; sẽ hoàn tất khi có cả điện và nước.";
                    button.setEnabled(true);
                    toast(message);
                    tab="bills";
                    showHome();
                    loadReadings();
                });
            } catch(Exception e) { runOnUiThread(() -> { button.setEnabled(true);result.setText(errorMessage(e)); }); }
        });
    }

    private void loadHome(boolean showLoading) {
        if(isLoading || token.isEmpty())return;isLoading=true;
        if(showLoading && content!=null){content.removeAllViews();content.addView(text("Đang tải hóa đơn…",14,MUTED,false));}
        executor.execute(() -> {
            try {
                JSONObject result=request(apiBase(),"/api/invoices",token,null);JSONArray invoices=result.optJSONArray("invoices");
                runOnUiThread(() -> { isLoading=false;if(content!=null&&"bills".equals(tab))renderInvoices(invoices); });
            } catch(Exception e) { runOnUiThread(() -> { isLoading=false;if(showLoading)toast(errorMessage(e)); }); }
        });
    }

    private void renderInvoices(JSONArray invoices) {
        content.removeAllViews();
        if(invoices==null||invoices.length()==0){content.addView(emptyCard("Chưa có hóa đơn. Hóa đơn sẽ xuất hiện tại đây khi quản lý tạo."));return;}
        for(int i=0;i<invoices.length();i++){
            JSONObject invoice=invoices.optJSONObject(i);if(invoice==null)continue;
            LinearLayout box=card();box.setPadding(dp(16),dp(16),dp(16),dp(16));
            box.addView(text("PHÒNG "+invoice.optString("room")+"  ·  "+invoice.optString("month"),10,GREEN,true));
            box.addView(text("Hóa đơn tháng "+invoice.optString("month"),18,INK,true),margin(0,5,0,0));
            TextView status=text(invoice.optString("status"),11,invoice.optString("status").equals("Chưa thanh toán")?GREEN:MUTED,true);box.addView(status,margin(0,4,0,0));
            box.addView(text(money(invoice.optDouble("total")),23,INK,true),margin(0,10,0,2));
            box.addView(text("Hạn thanh toán: "+invoice.optString("due"),11,MUTED,false),margin(0,0,0,9));
            JSONArray lines=invoice.optJSONArray("lines");if(lines!=null)for(int j=0;j<lines.length();j++){
                JSONObject line=lines.optJSONObject(j);if(line==null)continue;
                String detail=line.optString("name");String unit=line.optString("unit");
                if("kWh".equals(unit)||"m³".equals(unit))detail+="  ·  "+line.optDouble("qty")+" "+unit+" × "+money(line.optDouble("rate"));
                LinearLayout row=row();row.setPadding(0,dp(9),0,dp(9));row.addView(text(detail,12,MUTED,false),new LinearLayout.LayoutParams(0,-2,1));row.addView(text(money(line.optDouble("amount")),12,INK,true));box.addView(row);
                View divider=new View(this);divider.setBackgroundColor(BORDER);box.addView(divider,new LinearLayout.LayoutParams(-1,dp(1)));
            }
            content.addView(box,margin(0,0,0,12));
        }
    }

    private void loadReadings() {
        if(token.isEmpty())return;
        executor.execute(() -> { try {
            JSONObject r=request(apiBase(),"/api/readings",token,null);JSONArray rows=r.optJSONArray("readings");
            runOnUiThread(() -> {
                String electric="Chưa có chỉ số điện trước đó.",water="Chưa có chỉ số nước trước đó.";
                if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject x=rows.optJSONObject(i);if(x==null)continue;String label=x.optString("utility")+" gần nhất: "+x.optDouble("reading")+" ("+x.optString("status")+").";if("Điện".equals(x.optString("utility"))&&electric.startsWith("Chưa"))electric=label;if("Nước".equals(x.optString("utility"))&&water.startsWith("Chưa"))water=label;}
                if(electricReading!=null)electricReading.setHint(electric);if(waterReading!=null)waterReading.setHint(water);
            });
        }catch(Exception ignored){} });
    }

    private void loadNotifications() {
        if(token.isEmpty())return;
        executor.execute(() -> { try {
            JSONObject r=request(apiBase(),"/api/notifications",token,null);JSONArray rows=r.optJSONArray("notifications");
            runOnUiThread(() -> { content.removeAllViews();if(rows==null||rows.length()==0){content.addView(emptyCard("Bạn chưa có thông báo."));return;}
                for(int i=0;i<rows.length();i++){JSONObject n=rows.optJSONObject(i);if(n==null)continue;LinearLayout box=card();box.setPadding(dp(15),dp(14),dp(15),dp(14));box.addView(text(n.optString("title"),14,INK,true));box.addView(text(n.optString("body"),12,MUTED,false),margin(0,4,0,5));box.addView(text(n.optString("created_at"),10,MUTED,false));content.addView(box,margin(0,0,0,10));}
            });
        }catch(Exception e){runOnUiThread(()->toast(errorMessage(e)));} });
    }

    private JSONObject request(String base,String path,String auth,JSONObject body)throws Exception{
        URL url=new URL(base.replaceAll("/+$","")+path);HttpURLConnection conn=(HttpURLConnection)url.openConnection();conn.setConnectTimeout(10000);conn.setReadTimeout(15000);conn.setRequestProperty("Accept","application/json");
        if(auth!=null&&!auth.isEmpty())conn.setRequestProperty("Authorization","Bearer "+auth);
        if(body!=null){conn.setRequestMethod("POST");conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json; charset=utf-8");try(java.io.OutputStream out=conn.getOutputStream()){out.write(body.toString().getBytes("UTF-8"));}}
        int code=conn.getResponseCode();InputStream stream=code>=400?conn.getErrorStream():conn.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;while((n=stream.read(buffer))!=-1)bytes.write(buffer,0,n);stream.close();JSONObject response=new JSONObject(bytes.toString("UTF-8"));conn.disconnect();if(code>=400)throw new Exception(response.optString("error","Máy chủ từ chối yêu cầu."));return response;
    }

    private String apiBase(){return prefs.getString("server","");}
    private void logout(){executor.execute(()->{try{request(apiBase(),"/api/logout",token,new JSONObject());}catch(Exception ignored){}runOnUiThread(()->{token="";customerName="";prefs.edit().remove("token").remove("name").apply();showLogin();});});}
    private String money(double value){return currency.format(value)+" ₫";}
    private String errorMessage(Exception e){String m=e.getMessage();return m==null?"Không kết nối được máy chủ.":m;}
    private void setBusy(boolean busy){if(serverInput!=null)serverInput.setEnabled(!busy);if(usernameInput!=null)usernameInput.setEnabled(!busy);if(passwordInput!=null)passwordInput.setEnabled(!busy);}
    private void toast(String message){Toast.makeText(this,message,Toast.LENGTH_LONG).show();}
    private TextView emptyCard(String message){LinearLayout box=card();box.setPadding(dp(18),dp(22),dp(18),dp(22));TextView t=text(message,13,MUTED,false);box.addView(t);return t;}
    private LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    private LinearLayout row(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.HORIZONTAL);return l;}
    private LinearLayout card(){LinearLayout l=column();l.setBackground(round(Color.WHITE,18));return l;}
    private GradientDrawable round(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));d.setStroke(dp(1),BORDER);return d;}
    private TextView text(String value,int size,int color,boolean bold){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setGravity(Gravity.CENTER_VERTICAL);if(bold)t.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return t;}
    private EditText field(String hint,boolean secret){EditText e=new EditText(this);e.setSingleLine(true);e.setTextSize(14);e.setHint(hint);e.setPadding(dp(12),dp(10),dp(12),dp(10));e.setBackground(round(Color.rgb(251,253,251),10));if(secret)e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);else if(hint.toLowerCase().contains("đăng nhập")||hint.toLowerCase().contains("điện thoại"))e.setInputType(InputType.TYPE_CLASS_TEXT);return e;}
    private Button button(String label,boolean selected){Button b=new Button(this);b.setText(label);b.setTextSize(12);b.setAllCaps(false);b.setTextColor(selected?Color.WHITE:GREEN);b.setBackground(round(selected?GREEN:Color.WHITE,12));return b;}
    private Button primary(String label){Button b=new Button(this);b.setText(label);b.setTextSize(14);b.setAllCaps(false);b.setTypeface(Typeface.DEFAULT,Typeface.BOLD);b.setTextColor(Color.WHITE);b.setBackground(round(GREEN,12));return b;}
    private int dp(int v){return Math.round(v*getResources().getDisplayMetrics().density);}
    private LinearLayout.LayoutParams match(){return new LinearLayout.LayoutParams(-1,-2);}
    private LinearLayout.LayoutParams margin(int l,int t,int r,int b){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(dp(l),dp(t),dp(r),dp(b));return p;}
}
