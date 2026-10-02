import path from 'node:path';
import {startFixture} from '../fixture/server.mjs';
const fixture = await startFixture({port:Number(process.env.PORT || 8787), reportDir:path.resolve('report')});
console.log(JSON.stringify({pid:process.pid, app:fixture.url, report:fixture.url+'/report/'}));
for (const signal of ['SIGINT','SIGTERM']) process.on(signal, async()=>{await fixture.close();process.exit(0);});
