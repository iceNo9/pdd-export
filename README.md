<!--
 * @Author: CPBook 3222973652@qq.com
 * @Date: 2024-11-14 12:07:01
 * @LastEditors: CPBook 3222973652@qq.com
 * @LastEditTime: 2024-11-19 11:31:32
 * @FilePath: \pdd-export\README.md
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
# pdd-export

去https://googlechromelabs.github.io/chrome-for-testing/下载一个浏览器到项目根目录下，最终路径应该是在main.py的./chrome-win64
推荐https://storage.googleapis.com/chrome-for-testing-public/131.0.6778.69/win64/chrome-win64.zip

使用说明：
输入1和2设置起止时间，不设置默认导出全部订单
时间格式如2024 1 1 0 0 0，代表2024/01/01 00:00:00，时间部分可忽略

打包指令：nuitka --standalone --output-dir=build main.py
打包完后，把chrome-win64拷贝到打包的