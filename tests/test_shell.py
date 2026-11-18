"""Exercise the real Bash wrapper with a fake model and local-copy rsync stub."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from lpjregrowth.config import ROOT, write_text

BASH=shutil.which('bash') if os.name != 'nt' else r'C:\Program Files\Git\bin\bash.exe'

def shellpath(path):
    path=Path(path).resolve().as_posix()
    return '/'+path[0].lower()+path[2:] if len(path)>1 and path[1]==':' else path

@unittest.skipUnless(BASH and Path(BASH).is_file(),'Bash unavailable')
class ScratchTests(unittest.TestCase):
    def test_failure_recovery_and_copy_failure(self):
        for model_rc,copy_failure,expected in [(0,False,0),(7,False,7),(0,True,74)]:
            with self.subTest(model_rc=model_rc,copy_failure=copy_failure),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                work=root/'work';(work/'run1').mkdir(parents=True)
                write_text(work/'run1/guess.ins','test\n')
                binary=root/'guess'
                write_text(binary,f'#!/bin/bash\ncd "run$((SLURM_PROCID+1))" || exit 72\nprintf "fixture log\\n" > guess.log\nexit {model_rc}\n')
                binary.chmod(0o755)
                binpath=root/'bin';binpath.mkdir()
                write_text(binpath/'rsync','''#!/bin/bash
src=${@: -2:1}
dest=${@: -1}
if [[ "${FAIL_COPY:-0}" == 1 && "$src" == *lpj-* ]]; then exit 23; fi
mkdir -p "$dest" || exit 1
cp -a "$src/." "$dest/"
''')
                (binpath/'rsync').chmod(0o755)
                q=shlex.quote
                command='export PATH='+q(shellpath(binpath))+':"$PATH"; '
                command+='export SLURM_SUBMIT_DIR='+q(shellpath(work))+'; '
                command+='export TMP='+q(shellpath(root/'scratch'))+'; '
                command+='export SLURM_JOB_ID=123 SLURM_PROCID=0; unset OMPI_COMM_WORLD_RANK; '
                command+=f'export FAIL_COPY={int(copy_failure)}; '
                command+='bash '+q(shellpath(ROOT/'templates/mpi_run_guess_on_tmp.sh'))+' '+q(shellpath(binary))+' -parallel'
                result=subprocess.run([BASH,'-c',command],capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertEqual((work/'run1/model.exitcode').read_text().strip(),str(model_rc))
                self.assertEqual((work/'run1/copy.exitcode').read_text().strip(),'23' if copy_failure else '0')
                if not copy_failure:self.assertTrue((work/'run1/guess.log').is_file())
                self.assertTrue((root/'scratch/lpj-123/output/run1').exists())

if __name__=='__main__':unittest.main()
